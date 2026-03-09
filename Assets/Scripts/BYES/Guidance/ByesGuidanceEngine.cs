using UnityEngine;

namespace BYES.Guidance
{
    public enum GuidanceDirection
    {
        Unknown = 0,
        Left = 1,
        Right = 2,
        Center = 3,
        Stop = 4,
    }

    public readonly struct GuidanceOutput
    {
        public GuidanceOutput(GuidanceDirection direction, float strength)
        {
            Direction = direction;
            Strength = Mathf.Clamp01(strength);
        }

        public GuidanceDirection Direction { get; }
        public float Strength { get; }

        public override string ToString()
        {
            return $"{Direction.ToString().ToUpperInvariant()}({Strength:0.00})";
        }
    }

    public sealed class ByesGuidanceEngine : MonoBehaviour
    {
        [SerializeField] private float leftThreshold = 0.45f;
        [SerializeField] private float rightThreshold = 0.55f;
        [SerializeField] private float stopDistanceM = 0.6f;

        public GuidanceOutput Evaluate(float centerXNorm, float depthM = -1f)
        {
            if (depthM > 0f && depthM <= stopDistanceM)
            {
                return new GuidanceOutput(GuidanceDirection.Stop, 1f);
            }

            var clampedX = Mathf.Clamp01(centerXNorm);
            if (clampedX < leftThreshold)
            {
                var strength = Mathf.Clamp01((leftThreshold - clampedX) / Mathf.Max(0.01f, leftThreshold));
                return new GuidanceOutput(GuidanceDirection.Left, strength);
            }

            if (clampedX > rightThreshold)
            {
                var strength = Mathf.Clamp01((clampedX - rightThreshold) / Mathf.Max(0.01f, 1f - rightThreshold));
                return new GuidanceOutput(GuidanceDirection.Right, strength);
            }

            var centerStrength = 1f - Mathf.Clamp01(Mathf.Abs(clampedX - 0.5f) * 2f);
            return new GuidanceOutput(GuidanceDirection.Center, centerStrength);
        }
    }
}
