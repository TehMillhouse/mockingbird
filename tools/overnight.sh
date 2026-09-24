#!/usr/bin/env bash
# Overnight convergence and size study. Launch detached so it survives the editor session:
#   powershell -c "Start-Process bash -ArgumentList 'tools/overnight.sh' -WindowStyle Hidden"
# Progress: models/overnight/chain.log and models/overnight/<run>/train_log.jsonl
cd "$(dirname "$0")/.." || exit 1
mkdir -p models/overnight models/plots
{
  echo "START $(date)"
  uv run mb train --epochs 150 --patience 1000 --pos metric_rope --metric-emb \
    --out models/overnight/production --checkpoint model.pt > models/overnight/production.log 2>&1
  echo "STAGE1_DONE $(date)"
  uv run mb train --epochs 150 --patience 1000 --pos metric_rope --metric-emb --arch looped --d-model 192 --sandwich-norm \
    --out models/overnight/looped192 --checkpoint model.pt > models/overnight/looped192.log 2>&1
  echo "STAGE2_DONE $(date)"
  uv run mb train --epochs 60 --patience 1000 --pos metric_rope --metric-emb --d-model 384 \
    --out models/overnight/wide384 --checkpoint model.pt > models/overnight/wide384.log 2>&1
  echo "STAGE3_DONE $(date)"
  uv run python tools/compare_runs.py models/overnight/production models/overnight/looped192 models/overnight/wide384 2>&1 | grep -v -i warning
  uv run python tools/plot_runs.py models/plots/overnight.html models/overnight/production models/overnight/looped192 models/overnight/wide384
  for m in production looped192 wide384; do
    echo "== $m"
    uv run python tools/cadence_metric.py --skip-val --levels 96 --model models/overnight/$m/model.pt 2>&1 | grep -v -i warning
  done
  echo "CHAIN_DONE $(date)"
} > models/overnight/chain.log 2>&1
