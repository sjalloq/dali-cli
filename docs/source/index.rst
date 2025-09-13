DALI Controller API
===================

Overview
--------
This site documents your DALI network controller’s REST API. The reference is
generated directly from the controller’s OpenAPI (Swagger) schema.

Getting the OpenAPI schema
--------------------------
Fetch and place the schema at ``docs/source/openapi/openapi.json``:

.. code-block:: bash

   curl -fsS http://10.0.0.239/openapi.json -o docs/source/openapi/openapi.json || \
   curl -fsS http://10.0.0.239/swagger.json -o docs/source/openapi/openapi.json

If your controller only provides an interactive UI at ``/docs``, open it in a browser
and use the UI’s “Download JSON” option.

Build
-----
Install dependencies and build HTML docs:

.. code-block:: bash

   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   pip install -r docs/requirements.txt
   make -C docs html

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: API

   api/index

