#!/bin/bash

LOSS=$1
PERTURB=$2
PROB="portfolio"
SALPHA=$3
NS=$4

shift 4

for SEED in 6 7 8 9
do
  JOB_NAME="${PROB}_$SALPHA-${LOSS}_$NS-$PERTURB($SEED)"
  echo $JOB_NAME
  sbatch $@ -J "$JOB_NAME" --output="$JOB_NAME-%J.out" ~/bin/rsbatch.sh  main.py --problem=portfolio --loss=$LOSS --seed=$SEED --instances=400 --testinstances=400 --valfrac=0.5 --stocks=50 --stockalpha=$SALPHA --lr=0.01 --sampling=$PERTURB --samplingstd=0.1 --numsamples=$NS --losslr=0.001 --serial=True 
  sleep 5
done
