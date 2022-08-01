# Contributing

Thank you for contributing! This section describes the typical steps in
setting up a development environment.

## Setup a virtual environment

```
$ python3 -m venv venv
$ source venv/bin/activate
$ pip3 install -r requirements.txt
```

## Running the tests

From within your virtual environment:

```
$ py.tests
```

## Contributing

Committing the change will run all necessary formatting, type checking, and
linting. Prefer small PRs to make reviews easy to manage.
