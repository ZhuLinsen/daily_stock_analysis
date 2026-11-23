"""Compatibility settings that must run before PyInstaller's dependency hooks."""

import os


# NLTK 3.10's CWD import guard treats PyInstaller's bundled ``_internal``
# standard-library directory as application-controlled source when the frozen
# executable starts beside that directory. The frozen importer already fixes
# the module search roots, so disable only this incompatible NLTK guard inside
# packaged binaries. This custom hook runs before ``pyi_rth_nltk``.
os.environ.setdefault("NLTK_DISABLE_IMPORT_SECURITY", "1")
