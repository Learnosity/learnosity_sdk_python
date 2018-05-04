PYTHON=python3
VENV=.venv
VENVPATH=$(VENV)/$(shell uname)-$(shell uname -m)-sdk-python

define venv-activate
	. $(VENVPATH)/bin/activate; \
	unset PYTHONPATH
endef

prodbuild: test-version build
devbuild: build
build: venv
	$(call venv-activate); \
		$(PYTHON) setup.py sdist

test: test-unit test-integration-dev test-version
test-unit: venv pip-requirements-dev
	$(call venv-activate); \
		$(PYTHON) setup.py test

test-integration-dev: venv pip-tox
	$(call venv-activate); \
		tox

build-clean: real-clean

dist: distclean
	$(call venv-activate); \
		$(PYTHON) setup.py sdist; \
		$(PYTHON) setup.py bdist_wheel --universal
dist-upload: dist-check-version clean test dist-upload-twine
dist-check-version: PKG_VER=v$(shell sed -n "s/^.*VERSION\s\+=\s\+'\([^']\+\)'.*$$/\1/p" setup.py)
dist-check-version: GIT_TAG=$(shell git describe --tags)
dist-check-version:
ifeq ('$(shell echo $(GIT_TAG) | grep -qw "$(PKG_VER)")', '')
	$(error Version number $(PKG_VER) in setup.py does not match git tag $(GIT_TAG))
endif
dist-upload-twine: pip-requirements-dev dist # This target doesn't do any safety check!
	$(call venv-activate); \
		twine upload dist/*

clean: test-clean distclean
	find . -path __pycache__ -delete
	find . -name *.pyc -delete
test-clean:
	test ! -d .tox || rm -r .tox
distclean:
	test ! -d dist || rm -r dist
real-clean: clean
	test ! -d $(VENV) || rm -r $(VENV)
	test ! -d learnosity_sdk.egg-info || rm -r learnosity_sdk.egg-info

# Python environment and dependencies
venv: $(VENVPATH)
$(VENVPATH):
	virtualenv -p$(PYTHON) $(VENVPATH)
	$(call venv-activate); \
		pip install -e .

pip-requirements-dev: venv
	$(call venv-activate); \
		pip install -r requirements-dev.txt

pip-tox: venv
	$(call venv-activate); \
		pip install tox

.PHONY: dist
