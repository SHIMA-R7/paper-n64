param(
    [string]$ImageName = 'print-1200dpi.png',
    [string]$PrinterName = 'Brother DCP-J1270N Printer',
    [string]$DocumentTitle = 'Paper N64 calibration v1 - A4 actual size',
    [switch]$Monochrome,
    [string]$DevModeFile = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$taskImagePath = Join-Path $PSScriptRoot $ImageName
$taskImage = [System.Drawing.Image]::FromFile($taskImagePath)
$taskDocument = New-Object System.Drawing.Printing.PrintDocument
try {
    $taskDocument.PrinterSettings.PrinterName = $PrinterName
    if (-not $taskDocument.PrinterSettings.IsValid) { throw 'J1270N printer unavailable' }
    if($DevModeFile){
        $taskBytes=[System.IO.File]::ReadAllBytes((Join-Path $PSScriptRoot $DevModeFile))
        $taskHandle=[System.Runtime.InteropServices.Marshal]::AllocHGlobal($taskBytes.Length)
        try{
            [System.Runtime.InteropServices.Marshal]::Copy($taskBytes,0,$taskHandle,$taskBytes.Length)
            $taskDocument.PrinterSettings.SetHdevmode($taskHandle)
            $taskDocument.DefaultPageSettings.SetHdevmode($taskHandle)
        }finally{[System.Runtime.InteropServices.Marshal]::FreeHGlobal($taskHandle)}
    }
    $taskDocument.DocumentName = $DocumentTitle
    $taskDocument.PrinterSettings.Copies = 1
    $taskDocument.PrinterSettings.Duplex = [System.Drawing.Printing.Duplex]::Simplex
    $taskDocument.DefaultPageSettings.PaperSize = @($taskDocument.PrinterSettings.PaperSizes | Where-Object { $_.Kind -eq 'A4' })[0]
    $taskDocument.DefaultPageSettings.Color = -not $Monochrome
    $taskDocument.DefaultPageSettings.Landscape = $false
    $taskDocument.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(0,0,0,0)
    if(-not $DevModeFile){
        $taskDocument.DefaultPageSettings.PrinterResolution = @($taskDocument.PrinterSettings.PrinterResolutions | Where-Object { $_.Kind -eq 'High' })[0]
    }
    $taskDocument.PrintController = New-Object System.Drawing.Printing.StandardPrintController
    $taskDocument.add_PrintPage({
        param($sender, $eventArgs)
        $g = $eventArgs.Graphics
        $g.PageUnit = [System.Drawing.GraphicsUnit]::Display
        $g.TranslateTransform(-$eventArgs.PageSettings.HardMarginX, -$eventArgs.PageSettings.HardMarginY)
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
        $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
        $bounds = New-Object System.Drawing.RectangleF(0,0,(210/25.4*100),(297/25.4*100))
        $g.DrawImage($taskImage,$bounds)
        $eventArgs.HasMorePages = $false
    })
    $taskDocument.Print()
    Write-Output "Submitted one A4 page to $PrinterName, high quality, actual size. Monochrome=$Monochrome"
} finally {
    $taskDocument.Dispose()
    $taskImage.Dispose()
}
