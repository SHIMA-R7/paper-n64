param(
    [string]$ScannerName = 'Brother DCP-J1270N LAN',
    [string]$OutputDirectory = 'scans'
)
$ErrorActionPreference = 'Stop'
$taskDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($taskDirectory) | Out-Null
$taskManager = New-Object -ComObject WIA.DeviceManager
$taskInfo = @($taskManager.DeviceInfos) | Where-Object {
    ($_.Properties | Where-Object Name -eq 'Name').Value -eq $ScannerName
} | Select-Object -First 1
if(-not $taskInfo){throw "Scanner unavailable: $ScannerName"}
$taskDevice = $taskInfo.Connect()
$taskItem = $taskDevice.Items.Item(1)
$taskItem.Properties.Item('6146').Value = 1
$taskItem.Properties.Item('6147').Value = 1200
$taskItem.Properties.Item('6148').Value = 1200
$taskItem.Properties.Item('6149').Value = 0
$taskItem.Properties.Item('6150').Value = 0
$taskItem.Properties.Item('6151').Value = 9921
$taskItem.Properties.Item('6152').Value = 14031
$taskImage = $taskItem.Transfer('{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}')
$taskPath = Join-Path $taskDirectory ('scan-v8-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.bmp')
$taskImage.SaveFile($taskPath)
Write-Output $taskPath
Write-Output ("Pixels: {0}x{1}" -f $taskImage.Width,$taskImage.Height)
