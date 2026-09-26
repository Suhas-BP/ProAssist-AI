import win32evtlog
import win32evtlogutil
import win32security

# Query Windows Event Log for Audio
try:
    import win32evtlog
    server = 'localhost'
    logtype = 'Microsoft-Windows-Audio/Operational'
    hand = win32evtlog.EvtQuery(r"C:\Windows\System32\Winevt\Logs\Microsoft-Windows-Audio%4Operational.evtx", win32evtlog.EvtQueryFilePath)
    events = win32evtlog.EvtNext(hand, 10)
    for ev in events:
        xml = win32evtlog.EvtRender(ev, win32evtlog.EvtRenderEventXml)
        print(xml[:300])
except Exception as e:
    print('Error:', e)
