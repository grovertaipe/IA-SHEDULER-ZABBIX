WIDGET_DIR=aimaintenance
VERSION ?= $(shell git describe --tags --always --dirty)

zip:
	cd $(WIDGET_DIR) && zip -r ../zabbix-widget-aimaintenance-$(VERSION).zip .
