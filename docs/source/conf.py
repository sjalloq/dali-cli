import os
import sys
from datetime import datetime

project = "DALI Controller API"
author = ""
release = "0.1.0"
copyright = f"{datetime.now().year}, {author}"  # noqa

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    "sphinxcontrib.openapi",
    "sphinxcontrib.httpdomain",
]

autosectionlabel_prefix_document = True
templates_path = ["_templates"]
exclude_patterns = []

# Sphinx >= 5 uses root_doc; keep master_doc for older compat
root_doc = "index"

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
