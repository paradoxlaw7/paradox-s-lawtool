"""Optional local-only configuration. Reads credential invisibly and persists no file."""
import getpass,json,urllib.request
key=getpass.getpass('Local SiliconFlow credential (hidden): ')
request=urllib.request.Request('http://127.0.0.1:8766/api/config',data=json.dumps({'api_key':key,'model':'deepseek-ai/DeepSeek-V3.2','format':'auto'}).encode(),headers={'Content-Type':'application/json','X-Workspace-Request':'1'})
with urllib.request.urlopen(request,timeout=10):pass
key=None
print('Local model configured in service memory; no credential file written.')
