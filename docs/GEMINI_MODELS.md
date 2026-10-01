# Gemini model choices (paid API)

## Image generation / facade redesign

| Model | ID | Use? | Why |
| --- | --- | --- | --- |
| **Nano Banana Pro** | `gemini-3-pro-image` | **BEST quality** | Strongest photo edit / complex material instructions |
| **Nano Banana 2** | `gemini-3.1-flash-image` | **BEST balance** | Fast, high-volume edits; default non-HQ path |
| **Nano Banana** | `gemini-2.5-flash-image` | Good fallback | Stable older image model |
| Nano Banana 2 Lite | `gemini-3.1-flash-lite-image` | Optional cheap | Lower fidelity — not default |
| Imagen 4 | `imagen-4.0-*` | **Do not use** | Deprecated / shutting down |
| Text Flash/Pro | `gemini-3.8-flash`, `gemini-2.5-pro`, … | **Do not use for gen** | No image output |
| TTS / Live / Veo | `*-tts`, `*-live`, `veo-*` | **Do not use** | Wrong modality |
| Gemini 2.0 Flash | `gemini-2.0-flash` | **Do not use** | Shutdown |

App order: Pro image (HQ) → Flash Image → legacy 2.5 Flash Image → Cloudflare Lightning.

## Structure segmentation (boxes)

| Model | ID | Use? | Why |
| --- | --- | --- | --- |
| **Gemini 2.5 Pro** | `gemini-2.5-pro` | **BEST boxes** | Best structured bounding-box accuracy |
| Gemini 3.1 Pro | `gemini-3.1-pro-preview` | Strong alt | Newer; may be preview-gated |
| Gemini 3.8 Flash | `gemini-3.8-flash` | OK faster | Weaker boxes than Pro |
| Gemini 2.5 Flash | `gemini-2.5-flash` | OK budget | Noticeably weaker mAP |
| Flash-Lite | `*-flash-lite` | **Avoid** | Many invalid / weak boxes |
| `*-image` models | Nano Banana family | **Do not use** | Image generators, not detectors |

App order: Gemini detect → SegFormer (HF) → Grounded-SAM → OpenCV.

## Env

```bash
GEMINI_API_KEY=...
ENABLE_GEMINI_REDESIGN=true
ENABLE_GEMINI_DETECT=true
GEMINI_IMAGE_MODEL=gemini-3-pro-image
GEMINI_DETECT_MODEL=gemini-2.5-pro
```
