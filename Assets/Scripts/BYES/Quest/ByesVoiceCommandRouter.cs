using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesVoiceCommandRouter : MonoBehaviour
    {
        private static readonly Regex FindRegex = new Regex(
            "(find|look for|search|\u627e|\u627e\u4e00\u4e0b|\u5bfb\u627e|\u67e5\u627e)\\s*(?<concept>[a-zA-Z0-9\\u4e00-\\u9fa5 _-]+)?",
            RegexOptions.IgnoreCase | RegexOptions.Compiled);

        private static readonly string[] ReadKeywords =
        {
            "read", "ocr", "read text", "\u8bfb", "\u8bfb\u53d6", "\u5ff5\u4e00\u4e0b", "\u5ff5\u7ed9\u6211\u542c"
        };

        private static readonly string[] RecordStartKeywords =
        {
            "start record", "record start", "start recording", "\u5f00\u59cb\u5f55\u5236", "\u5f00\u59cb\u8bb0\u5f55"
        };

        private static readonly string[] RecordStopKeywords =
        {
            "stop record", "record stop", "stop recording", "\u505c\u6b62\u5f55\u5236", "\u505c\u6b62\u8bb0\u5f55"
        };

        private static readonly string[] PassthroughOnKeywords =
        {
            "passthrough on", "open passthrough", "turn on passthrough", "\u6253\u5f00\u900f\u89c6", "\u5f00\u542f\u900f\u89c6"
        };

        private static readonly string[] PassthroughOffKeywords =
        {
            "passthrough off", "close passthrough", "turn off passthrough", "\u5173\u95ed\u900f\u89c6"
        };

        private static readonly string[] GuidanceOnKeywords =
        {
            "start navigation", "navigation on", "guidance on", "\u5f00\u59cb\u5bfc\u822a", "\u5f00\u542f\u5bfc\u822a"
        };

        private static readonly string[] GuidanceOffKeywords =
        {
            "stop navigation", "navigation off", "guidance off", "\u505c\u6b62\u5bfc\u822a", "\u5173\u95ed\u5bfc\u822a"
        };

        public string LastTranscript { get; private set; } = "-";
        public string LastAction { get; private set; } = "-";

        public bool RouteTranscript(string transcript, ByesQuest3ConnectionPanelMinimal panel)
        {
            if (panel == null)
            {
                return false;
            }

            var raw = string.IsNullOrWhiteSpace(transcript) ? string.Empty : transcript.Trim();
            LastTranscript = string.IsNullOrWhiteSpace(raw) ? "-" : raw;
            if (string.IsNullOrWhiteSpace(raw))
            {
                LastAction = "noop(empty)";
                return false;
            }

            var lower = raw.ToLowerInvariant();

            if (ContainsAny(lower, ReadKeywords))
            {
                panel.TriggerReadTextOnceFromUi();
                LastAction = "ocr_once";
                return true;
            }

            var findMatch = FindRegex.Match(raw);
            if (findMatch.Success)
            {
                var concept = (findMatch.Groups["concept"]?.Value ?? string.Empty).Trim();
                if (string.IsNullOrWhiteSpace(concept))
                {
                    concept = "door";
                }

                panel.TriggerFindConceptFromUi(concept);
                LastAction = "find:" + concept;
                return true;
            }

            if (ContainsAny(lower, RecordStartKeywords))
            {
                panel.TriggerStartRecordFromUi();
                LastAction = "record_start";
                return true;
            }

            if (ContainsAny(lower, RecordStopKeywords))
            {
                panel.TriggerStopRecordFromUi();
                LastAction = "record_stop";
                return true;
            }

            if (ContainsAny(lower, PassthroughOnKeywords))
            {
                panel.SetPassthroughEnabled(true);
                LastAction = "passthrough_on";
                return true;
            }

            if (ContainsAny(lower, PassthroughOffKeywords))
            {
                panel.SetPassthroughEnabled(false);
                LastAction = "passthrough_off";
                return true;
            }

            if (ContainsAny(lower, GuidanceOnKeywords))
            {
                panel.SetAutoGuidance(true);
                LastAction = "guidance_on";
                return true;
            }

            if (ContainsAny(lower, GuidanceOffKeywords))
            {
                panel.SetAutoGuidance(false);
                LastAction = "guidance_off";
                return true;
            }

            LastAction = "noop(unmatched)";
            return false;
        }

        private static bool ContainsAny(string source, IReadOnlyList<string> keywords)
        {
            if (string.IsNullOrWhiteSpace(source) || keywords == null)
            {
                return false;
            }

            for (var i = 0; i < keywords.Count; i += 1)
            {
                var token = keywords[i];
                if (string.IsNullOrWhiteSpace(token))
                {
                    continue;
                }

                if (source.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }
            }

            return false;
        }
    }
}
