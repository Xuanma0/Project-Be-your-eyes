using System;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace BeYourEyes.Adapters.Networking
{
    [Serializable]
    public sealed class EventGuard
    {
        [SerializeField] private int allowedReorderSeq = 2;
        [SerializeField] private int defaultEventTtlMs = 1500;

        private long lastSeqSeen = -1;
        private long droppedExpired;
        private long droppedOutOfOrder;
        private long droppedByFallback;
        private long accepted;
        private string lastRejectReason = string.Empty;

        public int AllowedReorderSeq => Math.Max(0, allowedReorderSeq);
        public int DefaultEventTtlMs => Math.Max(100, defaultEventTtlMs);
        public long LastSeqSeen => lastSeqSeen;
        public long DroppedExpired => droppedExpired;
        public long DroppedOutOfOrder => droppedOutOfOrder;
        public long DroppedByFallback => droppedByFallback;
        public long Accepted => accepted;
        public string LastRejectReason => lastRejectReason;

        public bool ShouldAccept(JObject evt, long nowMs)
        {
            if (evt == null)
            {
                lastRejectReason = "null_event";
                return false;
            }

            var ttlMs = ResolveEventTtlMs(evt);
            var receivedAtMs = ResolveReceivedAtMs(evt, nowMs);
            if (nowMs - receivedAtMs > ttlMs)
            {
                droppedExpired++;
                lastRejectReason = "expired";
                return false;
            }

            if (TryReadLong(evt, "seq", out var seq))
            {
                var minAllowedSeq = lastSeqSeen - AllowedReorderSeq;
                if (lastSeqSeen >= 0 && seq < minAllowedSeq)
                {
                    droppedOutOfOrder++;
                    lastRejectReason = "out_of_order";
                    return false;
                }

                if (seq > lastSeqSeen)
                {
                    lastSeqSeen = seq;
                }
            }

            accepted++;
            lastRejectReason = string.Empty;
            return true;
        }

        public bool IsExpired(JObject evt, long nowMs)
        {
            if (evt == null)
            {
                return true;
            }

            var ttlMs = ResolveEventTtlMs(evt);
            var receivedAtMs = ResolveReceivedAtMs(evt, nowMs);
            return nowMs - receivedAtMs > ttlMs;
        }

        public int ResolveEventTtlMs(JObject evt)
        {
            if (evt != null && TryReadInt(evt, "ttlMs", out var ttlFromEvent) && ttlFromEvent > 0)
            {
                return Math.Max(100, ttlFromEvent);
            }

            if (evt != null && TryReadInt(evt, "_eventTtlMs", out var ttlFromMeta) && ttlFromMeta > 0)
            {
                return Math.Max(100, ttlFromMeta);
            }

            return DefaultEventTtlMs;
        }

        public void MarkFallbackDrop()
        {
            droppedByFallback++;
            lastRejectReason = "fallback_non_ok";
        }

        public void ResetRuntime()
        {
            lastSeqSeen = -1;
            droppedExpired = 0;
            droppedOutOfOrder = 0;
            droppedByFallback = 0;
            accepted = 0;
            lastRejectReason = string.Empty;
        }

        private static long ResolveReceivedAtMs(JObject evt, long fallbackNowMs)
        {
            if (evt != null && TryReadLong(evt, "_receivedAtMs", out var receivedAt) && receivedAt > 0)
            {
                return receivedAt;
            }

            return fallbackNowMs;
        }

        private static bool TryReadLong(JObject obj, string key, out long value)
        {
            value = -1;
            var token = obj?[key];
            if (token == null)
            {
                return false;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                value = token.Value<long>();
                return true;
            }

            return long.TryParse(token.ToString(), out value);
        }

        private static bool TryReadInt(JObject obj, string key, out int value)
        {
            value = -1;
            var token = obj?[key];
            if (token == null)
            {
                return false;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                value = token.Value<int>();
                return true;
            }

            return int.TryParse(token.ToString(), out value);
        }
    }
}
