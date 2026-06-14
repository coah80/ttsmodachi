import citra
import time
import utils

emu = citra.Citra()
import songConverter
import struct
import subprocess
import os
import signal
import io
import wave
'''
Status codes:
1 - Emulator is waiting for text
2 - Emulator is processing/generating audio
3 - Emulator finished generating audio and the data is ready
4 - Error
5 - Script has sent over the text data (set after code 1)
'''

# Lazy way to store data the game needs; these memory addresses aren't used by the game (hopefully)
audioRenderJobAddr=0x00af340d
textDataAddr=audioRenderJobAddr+0x3499D

audioRenderJobAddrJP=0x0090a27a
textDataAddrJP=audioRenderJobAddrJP+0x258

currentRom = None

emulatorProcess = None
structDef = "BBBBBBBBBiIiBB"

def env_value(name, default=None):
    value = os.environ.get(name)
    if value:
        return value
    if name.startswith("TTSMODACHI_"):
        legacy_value = os.environ.get("TALKMODACHI_" + name.removeprefix("TTSMODACHI_"))
        if legacy_value:
            return legacy_value
    return default

def getJobAddr():
    if currentRom == "JP":
        return audioRenderJobAddrJP
    return audioRenderJobAddr

def getTextAddr():
    if currentRom == "JP":
        return textDataAddrJP
    return textDataAddr

def readJob():
    structSize = struct.calcsize(structDef)
    data = emu.read_memory(getJobAddr(),structSize)
    unpacked = struct.unpack(structDef,data)
    return {
        "status": unpacked[0],
        "bpm": unpacked[1],
        "stretch": unpacked[2],
        "pitch": unpacked[3],
        "speed": unpacked[4],
        "quality": unpacked[5],
        "tone": unpacked[6],
        "accent": unpacked[7],
        "intonation": unpacked[8],
        "audioSize": unpacked[9],
        "audioData": unpacked[10],
        "allocatedSize": unpacked[11],
        "language": unpacked[12],
        "songDataSize": unpacked[13]
    }

def writeJobRaw(job,songData=None):
    structSize = struct.calcsize(structDef)
    data = struct.pack(structDef,job["status"],job["bpm"],job["stretch"],job["pitch"],job["speed"],job["quality"],job["tone"],job["accent"],job["intonation"],job["audioSize"],job["audioData"],job["allocatedSize"],job["language"],job["songDataSize"])
    emu.write_memory(getJobAddr(),data)
    if songData is not None:
        emu.write_memory(getJobAddr()+structSize+1,songData)

def calcFileLength(bytes):
    fLen = len(bytes)
    return fLen / (16000*2)

def waitForStatus(stat, timeout=15,setLanguage=None):
    current=-1
    start_time = time.time()
    poll_interval = float(env_value("TTSMODACHI_POLL_INTERVAL", "0.01"))
    language_set = False
    while current != stat:
        if setLanguage is not None and not language_set:
            job = readJob()
            job["language"] = setLanguage
            writeJobRaw(job)
            language_set = True
        time.sleep(poll_interval)
        current = emu.read_memory(getJobAddr(),1)[0]
        if time.time() - start_time > timeout:
            raise TimeoutError(f"Timed out waiting for status {stat}")

def setRom(name):
    global currentRom
    currentRom = name

def _cmdline_is_citra_port(cmdline, port):
    args = [part.decode("utf-8", "ignore") for part in cmdline.split(b"\0") if part]
    if not args:
        return False
    has_citra = any(os.path.basename(arg) == "citra" or arg.endswith("/citra") for arg in args)
    has_rom = any(arg.startswith("/opt/") and arg.endswith(".cxi") for arg in args)
    for index, arg in enumerate(args[:-1]):
        if arg == "-u" and args[index + 1] == str(port):
            return has_citra and has_rom
    return False

def cleanupCitraPort(port, exclude_pid=None):
    stale_pids = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        if exclude_pid is not None and pid == exclude_pid:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as file:
                cmdline = file.read()
        except OSError:
            continue
        if _cmdline_is_citra_port(cmdline, port):
            stale_pids.append(pid)
    for pid in stale_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.time() + 2
    while time.time() < deadline and stale_pids:
        remaining = []
        for pid in stale_pids:
            try:
                os.kill(pid, 0)
                remaining.append(pid)
            except ProcessLookupError:
                pass
        stale_pids = remaining
        if stale_pids:
            time.sleep(0.1)
    for pid in stale_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

def startEmulator(romname='US',setLanguage=None):
    global emulatorProcess
    global currentRom
    killEmulator()
    setRom(romname)
    work_dir = os.environ.get("CITRA_WORK_DIR", f"/tmp/ttsmodachi-{citra.CITRA_PORT}")
    config_dir = os.path.join(work_dir, "user", "config")
    os.makedirs(config_dir, exist_ok=True)
    with open("/config/sdl2-config.ini", "rb") as f:
        with open(os.path.join(config_dir, "sdl2-config.ini"), "wb") as f2:
            f2.write(f.read())

    max_runtime = int(os.environ.get("CITRA_MAX_RUNTIME_SECONDS", "0"))
    command = ['citra', f'/opt/{romname}.cxi', '-u',str(citra.CITRA_PORT)]
    if max_runtime > 0:
        command = ["timeout", f"{max_runtime}s"] + command
    citra_log_output = os.environ.get("CITRA_LOG_OUTPUT", "discard").lower()
    popen_kwargs = {"cwd": work_dir, "start_new_session": True}
    if citra_log_output in {"0", "false", "none", "quiet", "discard"}:
        popen_kwargs["stdout"] = subprocess.DEVNULL
        popen_kwargs["stderr"] = subprocess.DEVNULL
    cleanupCitraPort(citra.CITRA_PORT)
    emulatorProcess = subprocess.Popen(command, **popen_kwargs)
    connected = False
    start_time = time.time()
    startup_timeout = float(os.environ.get("CITRA_STARTUP_TIMEOUT", "90"))
    try:
        while not connected:
            if emulatorProcess.poll() is not None:
                raise RuntimeError(f"Citra exited before renderer connected with code {emulatorProcess.returncode}")
            if time.time() - start_time > startup_timeout:
                raise TimeoutError(f"Timed out waiting for Citra renderer on UDP port {citra.CITRA_PORT}")
            try:
                waitForStatus(1,timeout=min(5, startup_timeout),setLanguage=setLanguage)
                connected = True
            except TimeoutError:
                pass
    except Exception:
        killEmulator()
        raise

def killEmulator():
    global emulatorProcess
    process = emulatorProcess
    emulatorProcess = None
    if process is None:
        return
    try:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            except Exception:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    return
                except Exception:
                    process.kill()
                process.wait(timeout=5)
        else:
            process.wait(timeout=1)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        pass

def writeJob(bpm,stretch,pitch,speed,quality,tone,accent,intonation,songData,language):
    writeJobRaw({
        "status": 1,
        "bpm": bpm,
        "stretch": stretch,
        "pitch": pitch,
        "speed": speed,
        "quality": quality,
        "tone": tone,
        "accent": accent,
        "intonation": intonation,
        "audioSize": 0,
        "audioData": 0,
        "allocatedSize": 0,
        "language": language,
        "songDataSize": len(songData) if songData is not None else 0
    },songData)

def sendLyric(lyric,pitch=50,speed=50,quality=50,tone=50,accent=50,intonation=0,language=1):
    songData = songConverter.convertLyricParams(lyric["params"])
    sendText(lyric["data"],reset=False,pitch=pitch,speed=speed,quality=quality,tone=tone,accent=accent,intonation=intonation,songData=songData,bpm=lyric["bpm"],stretch=lyric["stretch"],language=language)

def sendText(text,reset=True,pitch=50,speed=50,quality=50,tone=50,accent=50,intonation=0,songData=None,bpm=120,stretch=50,language=1):
    #if reset:
    #    text=text+"\x1b\\mrk=1\\"

    text = text.replace("<bleep>","\x1b\\mrk=6\\").replace("</bleep>","\x1b\\mrk=7\\")
    text = text.replace("<echo>","\x1b\\mrk=4\\").replace("</echo>","\x1b\\mrk=5\\")
    text=text+"\0"
    emu.write_memory(getTextAddr(),text.encode('utf-16le'))

    writeJob(bpm,stretch,pitch,speed,quality,tone,accent,intonation,songData,language) # default values

    emu.write_memory(getJobAddr(),b"\x05") # set status to 5

def convertDataToMp3(data):
    sRate = 16000
    if currentRom == "JP":
        sRate = 0x58EF
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sRate)
        wav.writeframes(data)
    return out.getvalue()

def readDebugData():
    debugLoc = 0x004110f0
    debugSize = emu.read_memory(debugLoc,4)
    debugSize = int.from_bytes(debugSize,"little")
    debugData = emu.read_memory(debugLoc+4,debugSize)
    text = debugData.decode('utf-16le').replace("\x1b","*")
    print("Debug data: "+text)

def readRenderedAudio(timeout=15, chunk_size=citra.MAX_REQUEST_DATA_SIZE):
    start_time = time.time()
    metadata_timeout = float(env_value("TTSMODACHI_AUDIO_METADATA_TIMEOUT_SECONDS", "0.75"))
    metadata_deadline = start_time + max(0.0, metadata_timeout)
    poll_interval = float(env_value("TTSMODACHI_POLL_INTERVAL", "0.01"))

    while True:
        job = readJob()
        if job["audioSize"] > 0 and job["audioData"] != 0:
            break
        if time.time() >= metadata_deadline:
            return None
        time.sleep(poll_interval)

    total_size = job["audioSize"]
    address = job["audioData"]
    data = bytearray(total_size)
    bytes_read = 0
    
    while bytes_read < total_size:
        if time.time() - start_time > timeout:
            raise TimeoutError(f"timeout reading audio data after {bytes_read}/{total_size} bytes")
        
        remaining = total_size - bytes_read
        current_chunk_size = min(chunk_size, remaining)
        
        chunk = emu.read_memory(address + bytes_read, current_chunk_size)
        data[bytes_read:bytes_read + len(chunk)] = chunk
        bytes_read += len(chunk)
    
    return bytes(data)

def singText(text,pitch=50,speed=50,quality=50,tone=50,accent=50,intonation=0,language=1,ready_timeout=None):
    lyrics = songConverter.parseSong(text)
    fullData=b""
    for lyric in lyrics:
        waitForStatus(1,timeout=ready_timeout or 15)
        sendLyric(lyric,pitch=pitch,speed=speed,quality=quality,tone=tone,accent=accent,intonation=intonation,language=language)
        waitForStatus(3)
        #readDebugData()

        data = readRenderedAudio()
        if data is None:
            return None
        fullData+=data

        emu.write_memory(getJobAddr(),b"\x01") # set status to 1

    print("Length: "+str(calcFileLength(fullData))+"s")
    return convertDataToMp3(fullData)

def generateText(text,pitch=50,speed=50,quality=50,tone=50,accent=50,intonation=0,language=1,ready_timeout=None):
    waitForStatus(1,timeout=ready_timeout or 15,setLanguage=language)
    sendText(text,pitch=pitch,speed=speed,quality=quality,tone=tone,accent=accent,intonation=intonation,language=language)
    
    waitForStatus(3,timeout=10)

    data = readRenderedAudio()
    if data is None:
        return None

    emu.write_memory(getJobAddr(),b"\x01") # set status to 1

    print("Length: "+str(calcFileLength(data))+"s")
    
    return convertDataToMp3(data)
