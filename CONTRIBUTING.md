# Contributing

Thank you for contributing! This section describes the typical steps in
setting up a development environment.

## Setup a virtual environment

```
$ uv venv --python=3.13
$ source venv/bin/activate
$ uv pip install -r requirements_dev.txt
```

## Running the tests

From within your virtual environment:

```
$ pytest
```

## Contributing

Committing the change will run all necessary formatting, type checking, and
linting. Prefer small PRs to make reviews easy to manage.
