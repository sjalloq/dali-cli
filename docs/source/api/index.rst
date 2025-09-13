API Reference
=============

The sections below are rendered directly from the controller's OpenAPI schema.

Prerequisites
-------------
- Ensure the file ``docs/source/openapi/openapi.json`` (or ``.yaml``) exists.
- Ensure ``sphinxcontrib-openapi`` is installed (see ``docs/requirements.txt``).

OpenAPI
-------

.. note::
   If the build fails here, make sure you fetched the OpenAPI file to
   ``docs/source/openapi/openapi.json`` and that dependencies are installed.

.. openapi:: ../openapi/openapi.json
