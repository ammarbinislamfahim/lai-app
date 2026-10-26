"""Leaf Area and LAI measurement package."""
import importlib.abc
import importlib.util
import os
import sys


class _DirectFSFallbackFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> object:
        parts = fullname.split(".")
        search_dirs = path if path is not None else sys.path
        for d in search_dirs:
            if not d:
                d = os.getcwd()
            if not isinstance(d, str) or not d.startswith("/working_dir"):
                continue
            candidate_file = os.path.join(d, parts[-1] + ".py")
            if os.path.isfile(candidate_file):
                return importlib.util.spec_from_file_location(fullname, candidate_file)
            candidate_pkg = os.path.join(d, parts[-1], "__init__.py")
            if os.path.isfile(candidate_pkg):
                return importlib.util.spec_from_file_location(
                    fullname,
                    candidate_pkg,
                    submodule_search_locations=[os.path.join(d, parts[-1])],
                )
        return None


if not any(type(f).__name__ == "_DirectFSFallbackFinder" for f in sys.meta_path):
    sys.meta_path.append(_DirectFSFallbackFinder())
