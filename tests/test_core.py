import os
import tempfile
import unittest

from directory_size_counter_py import DirectorySummary, summarize


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, relative_path, contents=b""):
        path = os.path.join(self.root, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(contents)
        return path

    def test_empty_directory(self):
        result = summarize(self.root)
        self.assertIsInstance(result, DirectorySummary)
        self.assertEqual(result.path, self.root)
        self.assertEqual(result.total_bytes, 0)
        self.assertEqual(result.file_count, 0)
        self.assertEqual(result.subdirectories, {})

    def test_single_file(self):
        self._write("a.txt", b"hello")
        result = summarize(self.root)
        self.assertEqual(result.total_bytes, 5)
        self.assertEqual(result.file_count, 1)
        self.assertEqual(result.subdirectories, {})

    def test_nested_directories_aggregate_upward(self):
        self._write("top.txt", b"abc")
        self._write("sub/inner.txt", b"de")
        self._write("sub/deep/leaf.txt", b"f")

        result = summarize(self.root)

        self.assertEqual(result.file_count, 3)
        self.assertEqual(result.total_bytes, 6)
        self.assertIn("sub", result.subdirectories)

        sub = result.subdirectories["sub"]
        self.assertEqual(sub.file_count, 2)
        self.assertEqual(sub.total_bytes, 3)
        self.assertIn("deep", sub.subdirectories)

        deep = sub.subdirectories["deep"]
        self.assertEqual(deep.file_count, 1)
        self.assertEqual(deep.total_bytes, 1)
        self.assertEqual(deep.subdirectories, {})

    def test_subdirectory_keys_are_base_names(self):
        self._write("alpha/one.txt", b"1")
        self._write("beta/two.txt", b"22")
        result = summarize(self.root)
        self.assertEqual(set(result.subdirectories), {"alpha", "beta"})
        self.assertEqual(result.subdirectories["alpha"].path, os.path.join(self.root, "alpha"))
        self.assertEqual(result.subdirectories["beta"].path, os.path.join(self.root, "beta"))

    def test_symlink_is_counted_but_not_followed(self):
        target = self._write("target.txt", b"0123456789")
        link = os.path.join(self.root, "link.txt")
        os.symlink(target, link)

        result = summarize(self.root)

        # Two leaves: the target file and the symlink itself. The symlink's
        # own inode size is filesystem-dependent, so we only assert the count
        # and that the target's bytes are present at least once.
        self.assertEqual(result.file_count, 2)
        self.assertGreaterEqual(result.total_bytes, 10)

    def test_symlink_to_directory_is_not_descended(self):
        self._write("real/inner.txt", b"abc")
        link = os.path.join(self.root, "alias")
        os.symlink(os.path.join(self.root, "real"), link)

        result = summarize(self.root)

        # The walk must not follow ``alias`` into ``real``; otherwise the
        # inner file would be counted twice.
        self.assertEqual(result.file_count, 2)  # inner.txt + the symlink
        self.assertIn("real", result.subdirectories)
        self.assertNotIn("alias", result.subdirectories)
        self.assertEqual(result.subdirectories["real"].file_count, 1)
        self.assertEqual(result.subdirectories["real"].total_bytes, 3)

    def test_unreadable_directory_still_appears(self):
        if os.geteuid() == 0:
            self.skipTest("root bypasses permission checks")
        locked = os.path.join(self.root, "locked")
        os.makedirs(locked)
        self._write("locked/secret.txt", b"secret")
        os.chmod(locked, 0)
        try:
            result = summarize(self.root)
        finally:
            os.chmod(locked, 0o755)

        self.assertIn("locked", result.subdirectories)
        child = result.subdirectories["locked"]
        self.assertEqual(child.file_count, 0)
        self.assertEqual(child.total_bytes, 0)

    def test_missing_root_raises_file_not_found(self):
        missing = os.path.join(self.root, "does-not-exist")
        with self.assertRaises(FileNotFoundError):
            summarize(missing)

    def test_file_root_raises_not_a_directory(self):
        path = self._write("plain.txt", b"x")
        with self.assertRaises(NotADirectoryError):
            summarize(path)

    def test_to_dict_round_trips_structure(self):
        self._write("a.txt", b"aa")
        self._write("sub/b.txt", b"bbb")
        result = summarize(self.root)
        as_dict = result.to_dict()

        self.assertEqual(as_dict["path"], self.root)
        self.assertEqual(as_dict["total_bytes"], 5)
        self.assertEqual(as_dict["file_count"], 2)
        self.assertEqual(as_dict["subdirectories"]["sub"]["file_count"], 1)
        self.assertEqual(as_dict["subdirectories"]["sub"]["total_bytes"], 3)

    def test_zero_byte_files_are_counted(self):
        self._write("empty1.txt", b"")
        self._write("empty2.txt", b"")
        result = summarize(self.root)
        self.assertEqual(result.file_count, 2)
        self.assertEqual(result.total_bytes, 0)


if __name__ == "__main__":
    unittest.main()
