#!/bin/zsh
# A/B run on vLLM: ab_run.sh NAME SEQ(0|1) SET(dev|heldout) [gemini]
# needs LLM_BASE_URL, LLM_API_KEY (Apertus endpoint), FRAMEX_BINARY, PYTHONPATH with framex; gemini: GOOGLE_API_KEY;
# Opus judge: ANTHROPIC_API_KEY. Results in runs/ab/NAME (transcripts, regression.md, opus/judged.json).
cd "$(dirname "$0")/.."
export LLM_NAME=${LLM_NAME:-swiss-ai/Apertus-v1.5-8B} COACH_SEQUENCES=$2
if [ "$4" = gemini ]; then export SIM_PROVIDER=google SIM_HARD=1 SIM_SEED=v2 SIM_MODEL=gemini-flash-latest; fi
export RUNS_DIR=$PWD/../runs/ab/$1
mkdir -p $RUNS_DIR/opus
until [ "$(curl -s -m 20 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $LLM_API_KEY" $LLM_BASE_URL/models)" = 200 ]; do sleep 15; done
lane() { for s in "$@"; do FRAMEX_MODEL_CACHE=/tmp/ab-$1-$s-$RANDOM python3 -u -m eval.simulate $s; done }
if [ "$3" = dev ]; then
  lane S-01 S-02 S-24 S-14 > $RUNS_DIR/lane1.log 2>&1 &
  lane S-04 S-17 S-12 S-09 > $RUNS_DIR/lane2.log 2>&1 &
  lane S-05 S-13 S-15 > $RUNS_DIR/lane3.log 2>&1 &
  lane S-23 S-27 S-11 > $RUNS_DIR/lane4.log 2>&1 &
else
  lane S-03 S-06 S-25 S-18 > $RUNS_DIR/lane1.log 2>&1 &
  lane S-10 S-07 S-26 S-19 > $RUNS_DIR/lane2.log 2>&1 &
  lane S-16 S-08 S-20 > $RUNS_DIR/lane3.log 2>&1 &
  lane S-28 S-21 S-22 > $RUNS_DIR/lane4.log 2>&1 &
fi
wait
python3 -m eval.regression $RUNS_DIR > $RUNS_DIR/regression.md 2>&1
JUDGE_PROVIDER=anthropic RUNS_DIR=$RUNS_DIR/opus python3 -m eval.judge $RUNS_DIR/S-*.json > $RUNS_DIR/judge_opus.md 2>&1
