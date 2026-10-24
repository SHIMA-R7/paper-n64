param([switch]$Color)
$ErrorActionPreference='Stop'
$taskPrefix=if($Color){'best-quality-color'}else{'best-quality'}
Add-Type -AssemblyName ReachFramework
Add-Type -AssemblyName System.Printing
$taskPrinterName=(Get-Printer | Where-Object DriverName -eq 'Brother DCP-J1270N Printer' | Select-Object -First 1).Name
if(-not $taskPrinterName){throw 'Native J1270N driver unavailable'}
$taskServer=New-Object System.Printing.LocalPrintServer
$taskQueue=$taskServer.GetPrintQueue($taskPrinterName)
[xml]$taskXml=(New-Object System.IO.StreamReader($taskQueue.DefaultPrintTicket.GetXmlStream())).ReadToEnd()
$taskSettings=@{
    'psk:PageMediaType'='psk:Plain'
    'psk:PageOutputQuality'='psk:Photographic'
    'psk:PageOutputColor'='psk:Monochrome'
    'brpsk:PageAdvancedQualitySettings'='brpsk:BestQuality'
}
if($Color){$taskSettings['psk:PageOutputColor']='psk:Color'}
foreach($taskFeature in $taskXml.SelectNodes('//*[local-name()="Feature"]')){
    $taskKey=$taskFeature.GetAttribute('name')
    if($taskSettings.ContainsKey($taskKey)){
        $taskOption=$taskFeature.SelectSingleNode('./*[local-name()="Option"]')
        $taskOption.SetAttribute('name',$taskSettings[$taskKey])
    }
}
$taskStream=New-Object System.IO.MemoryStream
$taskXml.Save($taskStream);$taskStream.Position=0
$taskTicket=New-Object System.Printing.PrintTicket($taskStream)
$taskValidation=$taskQueue.MergeAndValidatePrintTicket($taskQueue.DefaultPrintTicket,$taskTicket)
$taskValidated=$taskValidation.ValidatedPrintTicket
$taskConverter=New-Object System.Printing.Interop.PrintTicketConverter($taskPrinterName,1)
$taskBytes=$taskConverter.ConvertPrintTicketToDevMode($taskValidated,[System.Printing.Interop.BaseDevModeType]::PrinterDefault)
[System.IO.File]::WriteAllBytes((Join-Path $PSScriptRoot ($taskPrefix+'.devmode')),$taskBytes)
$taskRoundTrip=$taskConverter.ConvertDevModeToPrintTicket($taskBytes)
$taskRoundTrip.SaveTo((New-Object System.IO.FileStream((Join-Path $PSScriptRoot ($taskPrefix+'-effective.xml')),[System.IO.FileMode]::Create)))
[xml]$taskEffective=$taskRoundTrip.GetXmlStream() | ForEach-Object { (New-Object System.IO.StreamReader($_)).ReadToEnd() }
foreach($taskFeature in $taskEffective.SelectNodes('//*[local-name()="Feature"]')){
    $taskKey=$taskFeature.GetAttribute('name')
    if($taskSettings.ContainsKey($taskKey)){
        $taskActual=$taskFeature.SelectSingleNode('./*[local-name()="Option"]').GetAttribute('name')
        Write-Output "$taskKey=$taskActual"
        if($taskActual -ne $taskSettings[$taskKey]){ throw "Driver changed requested setting $taskKey" }
    }
}
Write-Output "DevMode verified: $($taskBytes.Length) bytes. Printer defaults unchanged."
