# HK 3D Converter
Upload -> Preview -> Optional Rig -> Convert -> Download.

## 1. Run the backend (needs Assimp + Blender)
Docker: `docker build -t hk3d . && docker run -p 8000:8000 hk3d`
Local:  `apt install assimp-utils blender && pip install -r backend/requirements.txt && uvicorn backend.main:app --host 0.0.0.0 --port 8000`
Open http://localhost:8000 for the web version.

## 2. Build the APK
Push to GitHub -> Actions -> "Build APK" -> download artifact `HK3DConverter-debug-apk`.
Local (JDK 17 + Android SDK): `npm install && npm run build && npx cap add android && npx cap sync android && cd android && ./gradlew assembleDebug`
In the app: Settings -> Server address = your backend URL (e.g. http://192.168.1.10:8000).

## Where things happen
- Upload: frontend `upload()`, backend `/api/upload` (validation: converter/engine.py `inspect`)
- Conversion: converter/engine.py `convert_file`
- Rigging: rigging/rig.py + rigging/blender_rig.py
- Download: frontend `dl()`, backend `/api/download`, `/api/zip`

## Limits
- Preview uses three.js from a CDN; vendor it for fully offline use.
- Auto-rig is a heuristic for upright T/A-pose humanoids only.
- "Optimize" = Assimp post-processing; texture compression is not implemented.
- Android save: writes to Documents/HK3D and opens the share/save sheet.
- 
