# The submission project lives in track_2a/. Forward existing repository-root commands.
.DEFAULT_GOAL := run
TARGETS := run run-gpu stop chat voice-setup eval report lint check test test-unit test-integration test-docker
.PHONY: $(TARGETS)

$(TARGETS):
	@$(MAKE) --no-print-directory -C track_2a $@
