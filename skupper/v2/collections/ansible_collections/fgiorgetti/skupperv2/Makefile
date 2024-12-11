IMAGES = default
#IMAGES = default fedora40
#IMAGES = default alpine320 fedora40 ubuntu2204 ubuntu2404
#PYTHON = 3.12
PYTHON = 3.13

all: clean unit coverage

clean:
	rm -rf tests/output

.PHONY: unit
unit:
	ansible-test units --color --coverage --python $(PYTHON) -v

.PHONY: unit-docker
unit-docker: $(foreach img,$(IMAGES),unit-docker-$(img))
unit-docker-%: clean
	ansible-test units --coverage --docker "$*" --python $(PYTHON) -v

integration:
	techo ansible-test integration --docker default -v

coverage:
	ansible-test coverage html
