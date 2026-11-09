#!/bin/bash
# single 模式在 medium/human 开发集上的运行 + 自动评分（补 single/multi 对比数据）
set -u
cd /Users/yangchenzi/Documents/hkust_semi1_NLP/multi-agent-travel-planner
export PATH="/opt/homebrew/bin:$PATH"
RESULTS=/Users/yangchenzi/Documents/hkust_semi1_NLP/multi-agent-travel-planner/runs/single_mh_results.txt
echo "=== single medium/human run+score 开始 $(date) ===" > "$RESULTS"

run_one() {
  split="$1"; uid="$2"
  echo "" >> "$RESULTS"
  echo "### $split $uid @ $(date)" >> "$RESULTS"
  out=$(.venv/bin/python -m lab.cli run --mode single --transport mcp --split "$split" --uid "$uid" 2>&1)
  echo "$out" >> "$RESULTS"
  run_dir=$(printf '%s\n' "$out" | sed -n 's/^Results: //p')
  if [ -n "$run_dir" ]; then
    echo "--- 评分 ---" >> "$RESULTS"
    .venv/bin/python -m lab.evaluate "$run_dir" 2>&1 | tee -a "$RESULTS" >/dev/null
  else
    echo "!!! 未得到 run_dir，跳过评分" >> "$RESULTS"
  fi
}

run_one medium e20241028160842228543
run_one medium e20241028160845920703
run_one medium e20241028160848776495
run_one human h20241029143447759844
run_one human h20241029143450090032
run_one human h20241029143451793119

echo "" >> "$RESULTS"
echo "=== single medium/human 全部完成 $(date) ===" >> "$RESULTS"
