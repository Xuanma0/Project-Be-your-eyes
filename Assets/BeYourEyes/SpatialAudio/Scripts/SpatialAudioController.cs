using UnityEngine;
using UnityEngine.InputSystem;
public class SpatialAudioController : MonoBehaviour
{
    // 公开变量，在Unity编辑器中可方便地拖拽赋值
    public GameObject audioSourceCube; // 关联带有AudioSource的Cube  
    public float moveSpeed = 1f; // 移动速度
    private AudioSource audioSource;
    private bool isPlaying = false;

    void Start()
    {
        // 获取AudioSource组件，确保不为空
        if (audioSourceCube != null)
        {
            audioSource = audioSourceCube.GetComponent<AudioSource>();
            if (audioSource == null)
            {
                Debug.LogError("AudioSourceCube上没有找到AudioSource组件！");
            }
        }
        else
        {
            Debug.LogError("请将AudioSourceCube拖拽到脚本的公开变量上！");
        }

        // 初始放置：将Cube放在右前方1米，高度0.5米处
        PlaceAudioSourceAt(new Vector3(1f, 0.5f, 1f));
    }

    void Update()
    {
        if (Keyboard.current.spaceKey.wasPressedThisFrame)
        {
            ToggleAudio();
        }
        //移动物体
        if (Keyboard.current.wKey.isPressed)
        {
            audioSourceCube.transform.Translate(Vector3.forward * moveSpeed * Time.deltaTime);
        }
        if (Keyboard.current.sKey.isPressed)
        {
            audioSourceCube.transform.Translate(Vector3.back * moveSpeed * Time.deltaTime);
        }
        if (Keyboard.current.aKey.isPressed)
        {
            audioSourceCube.transform.Translate(Vector3.left * moveSpeed * Time.deltaTime);
        }
        if (Keyboard.current.dKey.isPressed)
        {
            audioSourceCube.transform.Translate(Vector3.right * moveSpeed * Time.deltaTime);
        }
        if (Keyboard.current.qKey.isPressed)
        {
            audioSourceCube.transform.Translate(Vector3.up * moveSpeed * Time.deltaTime);
        }
        if (Keyboard.current.eKey.isPressed)
        {
            audioSourceCube.transform.Translate(Vector3.down * moveSpeed * Time.deltaTime);
        }
    }

    // 放置声源到指定世界坐标
    void PlaceAudioSourceAt(Vector3 position)
    {
        if (audioSourceCube != null)
        {
            audioSourceCube.transform.position = position;
        }
    }

    // 切换音频播放状态
    public void ToggleAudio()
    {
        if (audioSource == null) return;

        isPlaying = !isPlaying;
        if (isPlaying)
        {
            audioSource.Play();
            Debug.Log("空间音频开始播放，位置：" + audioSourceCube.transform.position);
        }
        else
        {
            audioSource.Stop();
            Debug.Log("空间音频停止。");
        }
    }
}