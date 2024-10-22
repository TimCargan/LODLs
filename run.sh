#!/bin/bash

LOSS=$1
PERTURB=$2
PROB=$3
START=$4
STOP=$5

shift 5

 
for SEED_IX in $(seq $START $STOP)
do
  JOB_NAME="$PROB-x2-$LOSS-$PERTURB($SEED_IX)"
  echo $JOB_NAME
  SEED=$(sed -n "${SEED_IX}{p;q;}" seeds)
  sbatch $@ -J "$JOB_NAME" --output="$JOB_NAME-%J.out" ~/bin/rsbatch.sh main.py --problem=budgetalloc --loss=$LOSS --seed=$SEED --instances=200 --testinstances=500 --valfrac=0.2 --numitems=5 --budget=2 --sampling=$PERTURB --numsamples=512 --losslr=0.1 --serial=False
  sleep 5
done
