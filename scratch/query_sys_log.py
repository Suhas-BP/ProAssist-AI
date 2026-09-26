import subprocess
script = """
Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddHours(-6)} -ErrorAction SilentlyContinue | Where-Object { $_.Message -match 'audio|sound|mute' } | Select-Object TimeCreated, Id, Message
"""
res = subprocess.run(["powershell", "-Command", script], capture_output=True, text=True)
print("Output:", res.stdout.strip())
