# Publish to PyPI

Sign in to your PyPI maintainer account and configure a pending/trusted publisher for project `waix-python`, this GitHub repository, workflow `publish.yml`, environment `pypi`. Add required reviewers to the GitHub environment. Dispatch the workflow at the reviewed version tag. It builds a wheel and source distribution, validates them with Twine and publishes using OIDC; no long-lived PyPI token is stored.

Inspect the first package files and metadata before publication. Versions cannot be reused after deletion. Documentation: https://docs.pypi.org/trusted-publishers/.
