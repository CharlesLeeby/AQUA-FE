#pragma once
#include <atomic>
#include <chrono>
#include <algorithm>
#include "keyframe.h"

bool aquaLearnedMode();
int aquaLearnedCandidate(int query, double time);
void aquaRecordBow(int query, double time, const DBoW2::QueryResults &results);
void aquaRecordVerification(KeyFrame *frame, int candidate, bool passed, double seconds);
void aquaOptimizationDone(int index);
