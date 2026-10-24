$ErrorActionPreference='Stop'
Add-Type -AssemblyName ReachFramework
Add-Type -AssemblyName System.Printing
$taskPrinterName=(Get-Printer | Where-Object DriverName -eq 'Brother DCP-J1270N Printer' | Select-Object -First 1).Name
if(-not $taskPrinterName){throw 'Native J1270N driver unavailable'}
[xml]$taskXml=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'best-quality-color-effective.xml') -Raw -Encoding UTF8
$taskChanged=0
foreach($taskFeature in $taskXml.SelectNodes('//*[local-name()="Feature"]')){
    if($taskFeature.GetAttribute('name') -eq 'brpsk:PageBidirPrint'){
        $taskFeature.SelectSingleNode('./*[local-name()="Option"]').SetAttribute('name','brpsk:Off')
        $taskChanged++
    }
}
if($taskChanged -ne 1){throw 'Expected one bidirectional printing feature'}
$taskStream=New-Object System.IO.MemoryStream
$taskXml.Save($taskStream);$taskStream.Position=0
$taskTicket=New-Object System.Printing.PrintTicket($taskStream)
$taskServer=New-Object System.Printing.LocalPrintServer
$taskQueue=$taskServer.GetPrintQueue($taskPrinterName)
$taskValidation=$taskQueue.MergeAndValidatePrintTicket($taskQueue.DefaultPrintTicket,$taskTicket)
$taskConverter=New-Object System.Printing.Interop.PrintTicketConverter($taskPrinterName,1)
$taskBytes=$taskConverter.ConvertPrintTicketToDevMode($taskValidation.ValidatedPrintTicket,[System.Printing.Interop.BaseDevModeType]::PrinterDefault)
$taskRoundTrip=$taskConverter.ConvertDevModeToPrintTicket($taskBytes)
[xml]$taskEffective=(New-Object System.IO.StreamReader($taskRoundTrip.GetXmlStream())).ReadToEnd()
$taskExpected=@{'brpsk:PageBidirPrint'='brpsk:Off';'psk:PageMediaType'='psk:Plain';'psk:PageOutputQuality'='psk:Photographic';'psk:PageOutputColor'='psk:Color';'brpsk:PageAdvancedQualitySettings'='brpsk:BestQuality'}
foreach($taskFeature in $taskEffective.SelectNodes('//*[local-name()="Feature"]')){
    $taskKey=$taskFeature.GetAttribute('name')
    if($taskExpected.ContainsKey($taskKey)){
        $taskActual=$taskFeature.SelectSingleNode('./*[local-name()="Option"]').GetAttribute('name')
        Write-Output "$taskKey=$taskActual"
        if($taskActual -ne $taskExpected[$taskKey]){throw "Driver changed requested setting $taskKey"}
        $taskExpected.Remove($taskKey)
    }
}
if($taskExpected.Count){throw 'Driver omitted required setting'}
[System.IO.File]::WriteAllBytes((Join-Path $PSScriptRoot 'best-quality-color-unidirectional.devmode'),$taskBytes)
$taskRoundTrip.SaveTo((New-Object System.IO.FileStream((Join-Path $PSScriptRoot 'best-quality-color-unidirectional-effective.xml'),[System.IO.FileMode]::Create)))
Write-Output 'Job-specific unidirectional DEVMODE verified. Printer defaults unchanged.'
