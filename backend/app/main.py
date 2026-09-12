from contextlib import asynccontextmanager
import asyncio
import time
from pathlib import Path
import uuid
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from .config import ROOT, settings
from .models.schemas import SessionCreate, URLSource, Calibration, Snapshot, TrackRecord, PassageEvent, PassageSummary
from .services.sessions import Session, sessions
from .video.sources import discover_demo, resolve_stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    for session in list(sessions.values()):
        await session.close()
    sessions.clear()


app = FastAPI(title='SalmonSight', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000', 'http://127.0.0.1:3000'], allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['*'])


def get_session(session_id: str) -> Session:
    if session_id not in sessions:
        raise HTTPException(404, 'Session not found. Create a new analysis session.')
    session = sessions[session_id]
    session.last_access = time.monotonic()
    return session


@app.get('/api/health')
def health():
    video, cache = discover_demo()
    model = Path(settings.fishial_model_path if settings.detector_backend == 'fishial' else settings.local_model_path)
    model = model if model.is_absolute() else ROOT / model
    return {'status': 'ok', 'detector_backend': settings.detector_backend, 'model_configured': model.is_file(), 'inference_device': settings.inference_device, 'demo_video_available': video is not None, 'cache_available': cache is not None, 'simulation_available': True}


@app.post('/api/sessions', response_model=Snapshot)
async def create_session(body: SessionCreate = SessionCreate()):
    # Keep this local workstation demo bounded; never evict running analyses.
    if len(sessions) >= 12:
        idle = sorted((s for s in sessions.values() if not s.running), key=lambda s: s.last_access)
        if not idle:
            raise HTTPException(429, 'Too many running sessions. Pause one before creating another.')
        oldest = idle[0]
        await oldest.close()
        sessions.pop(oldest.id, None)
    try:
        session = await asyncio.to_thread(Session, body.source)
    except (ValueError, OSError) as exc:
        message = str(exc) if str(exc) else 'Unable to connect to this stream. Try again or choose another source.'
        raise HTTPException(422, message) from None
    sessions[session.id] = session
    await session.start_display()
    if body.source == 'demo':
        await session.start()
    return session.snapshot()


@app.get('/api/sessions/{session_id}', response_model=Snapshot)
async def read_session(session_id: str):
    return get_session(session_id).snapshot()


@app.post('/api/sessions/{session_id}/start', response_model=Snapshot)
async def start(session_id: str):
    session = get_session(session_id)
    async with session.lock:
        try:
            await session.start()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    return session.snapshot()


@app.post('/api/sessions/{session_id}/pause', response_model=Snapshot)
async def pause(session_id: str):
    session = get_session(session_id)
    async with session.lock:
        await session.stop()
    return session.snapshot()


@app.post('/api/sessions/{session_id}/calibration', response_model=Snapshot)
async def calibrate(session_id: str, body: Calibration):
    session = get_session(session_id)
    async with session.lock:
        session.calibration = body
        session.calibration_required = False
        await session.reset()
    return session.snapshot()


@app.post('/api/sessions/{session_id}/source', response_model=Snapshot)
async def upload(session_id: str, file: UploadFile = File(...)):
    session = get_session(session_id)
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ('.mp4', '.mov', '.avi'):
        raise HTTPException(415, 'Upload an MP4, MOV, or AVI video.')
    directory = ROOT / 'data/uploads'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{uuid.uuid4().hex}{suffix}'
    size = 0
    try:
        with path.open('wb') as dest:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 1024 * 1024 * 1024:
                    raise HTTPException(413, 'Video exceeds the 1 GB local upload limit.')
                dest.write(chunk)
        async with session.lock:
            await session.replace_source(
                path,
                display_name=Path(file.filename or 'Uploaded footage').name,
                source_type='upload',
                calibration_required=True,
            )
        return session.snapshot()
    except (ValueError, OSError) as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, 'Could not read the uploaded video. Try H.264 MP4.') from None
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.post('/api/sessions/{session_id}/source/url', response_model=Snapshot)
async def connect_url(session_id: str, body: URLSource):
    session = get_session(session_id)
    try:
        source = await asyncio.to_thread(resolve_stream, body.url)
        async with session.lock:
            await session.replace_source(
                source,
                display_name=source.display_name,
                source_type='live' if source.is_live else 'stream',
                calibration_required=True,
            )
        return session.snapshot()
    except (ValueError, OSError):
        raise HTTPException(422, 'Unable to connect to this stream. Try again or choose another source.') from None


@app.get('/api/sessions/{session_id}/summary', response_model=PassageSummary)
async def summary(session_id: str):
    return get_session(session_id).snapshot()['summary']


@app.get('/api/sessions/{session_id}/tracks', response_model=list[TrackRecord])
async def tracks(session_id: str):
    return get_session(session_id).snapshot(lightweight=False)['tracks']


@app.get('/api/sessions/{session_id}/events', response_model=list[PassageEvent])
async def events(session_id: str):
    return get_session(session_id).snapshot()['events']


@app.delete('/api/sessions/{session_id}')
async def delete_session(session_id: str):
    session = get_session(session_id)
    await session.close()
    sessions.pop(session_id, None)
    return {'deleted': True}


@app.get('/api/sessions/{session_id}/original')
async def original(session_id: str):
    session = get_session(session_id)
    if not isinstance(session.video, Path):
        raise HTTPException(404, 'No local video for this session.')
    return FileResponse(session.video)


@app.get('/api/sessions/{session_id}/video')
async def video_frames(session_id: str):
    session = get_session(session_id)
    if not session.processor.reader:
        raise HTTPException(404, 'Illustrative simulation has no recorded video.')

    async def frames():
        previous = None
        while session.id in sessions:
            current = session.processor.jpeg
            if current and current is not previous:
                previous = current
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + current + b'\r\n'
            # Display cadence is independent of detector cadence. The endpoint
            # only publishes the newest JPEG and never buffers historical frames.
            await asyncio.sleep(1 / 60)

    return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame', headers={'Cache-Control': 'no-store'})


@app.websocket('/ws/sessions/{session_id}')
async def websocket(websocket: WebSocket, session_id: str):
    if session_id not in sessions:
        await websocket.close(code=1008, reason='Session not found')
        return
    await websocket.accept()
    session = sessions[session_id]
    previous_tracks = {}
    previous_timestamp = -1.
    try:
        while session_id in sessions:
            packet = session.snapshot()
            if packet['timestamp'] < previous_timestamp:
                previous_tracks.clear()
            previous_timestamp = packet['timestamp']
            changed = []
            current_tracks = {}
            for track in packet['tracks']:
                signature = (track['last_seen'], track['active'], track['status'])
                current_tracks[track['id']] = signature
                if previous_tracks.get(track['id']) != signature:
                    changed.append(track)
            previous_tracks = current_tracks
            packet['tracks'] = changed
            packet['events'] = packet['events'][-20:]
            await websocket.send_json(packet)
            await asyncio.sleep(1 / session.processor.sample_fps)
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
