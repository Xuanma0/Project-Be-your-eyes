using System;
using System.Collections.Generic;
using UnityEngine;

namespace BYES.Telemetry
{
    public sealed class ByesHitchMonitor : MonoBehaviour
    {
        private readonly struct FrameSample
        {
            public FrameSample(float timestampSec, float dtSec)
            {
                TimestampSec = timestampSec;
                DtSec = dtSec;
            }

            public float TimestampSec { get; }
            public float DtSec { get; }
        }

        [SerializeField] private float windowSeconds = 30f;
        [SerializeField] private float hitchThresholdMs = 30f;
        [SerializeField] private float statsRefreshSeconds = 1f;

        private readonly Queue<FrameSample> _samples = new Queue<FrameSample>(4096);
        private float _sumDtSec;
        private float _nextStatsRefreshAt;
        private int _gc0Prev;
        private int _gc1Prev;
        private int _gc2Prev;

        public int HitchCount30s { get; private set; }
        public float WorstDt30sMs { get; private set; }
        public float AvgDt30sMs { get; private set; }
        public int Gc0Delta { get; private set; }
        public int Gc1Delta { get; private set; }
        public int Gc2Delta { get; private set; }

        private void OnEnable()
        {
            _samples.Clear();
            _sumDtSec = 0f;
            HitchCount30s = 0;
            WorstDt30sMs = 0f;
            AvgDt30sMs = 0f;

            _gc0Prev = GC.CollectionCount(0);
            _gc1Prev = GC.CollectionCount(1);
            _gc2Prev = GC.CollectionCount(2);
            Gc0Delta = 0;
            Gc1Delta = 0;
            Gc2Delta = 0;
            _nextStatsRefreshAt = Time.unscaledTime + Mathf.Max(0.2f, statsRefreshSeconds);
        }

        private void Update()
        {
            var nowSec = Time.unscaledTime;
            var dtSec = Mathf.Max(0f, Time.unscaledDeltaTime);

            _samples.Enqueue(new FrameSample(nowSec, dtSec));
            _sumDtSec += dtSec;
            TrimOldSamples(nowSec);

            if (nowSec < _nextStatsRefreshAt)
            {
                return;
            }

            RecalculateStats();
            _nextStatsRefreshAt = nowSec + Mathf.Max(0.2f, statsRefreshSeconds);
        }

        private void TrimOldSamples(float nowSec)
        {
            var keepWindow = Mathf.Max(5f, windowSeconds);
            while (_samples.Count > 0)
            {
                var oldest = _samples.Peek();
                if (nowSec - oldest.TimestampSec <= keepWindow)
                {
                    break;
                }

                _sumDtSec = Mathf.Max(0f, _sumDtSec - oldest.DtSec);
                _samples.Dequeue();
            }
        }

        private void RecalculateStats()
        {
            if (_samples.Count <= 0)
            {
                HitchCount30s = 0;
                WorstDt30sMs = 0f;
                AvgDt30sMs = 0f;
            }
            else
            {
                var hitchThresholdSec = Mathf.Max(0.001f, hitchThresholdMs / 1000f);
                var hitchCount = 0;
                var worstDtSec = 0f;

                foreach (var sample in _samples)
                {
                    if (sample.DtSec > hitchThresholdSec)
                    {
                        hitchCount += 1;
                    }

                    if (sample.DtSec > worstDtSec)
                    {
                        worstDtSec = sample.DtSec;
                    }
                }

                HitchCount30s = hitchCount;
                WorstDt30sMs = worstDtSec * 1000f;
                AvgDt30sMs = (_sumDtSec / Mathf.Max(1, _samples.Count)) * 1000f;
            }

            var gc0 = GC.CollectionCount(0);
            var gc1 = GC.CollectionCount(1);
            var gc2 = GC.CollectionCount(2);
            Gc0Delta = Math.Max(0, gc0 - _gc0Prev);
            Gc1Delta = Math.Max(0, gc1 - _gc1Prev);
            Gc2Delta = Math.Max(0, gc2 - _gc2Prev);
            _gc0Prev = gc0;
            _gc1Prev = gc1;
            _gc2Prev = gc2;
        }
    }
}
