# Trendyol 3D mağaza analizini bu bilgisayarda haftada bir çalıştıran Windows görevini kurar.
# Çalıştırma (PowerShell, proje klasöründe):
#   powershell -ExecutionPolicy Bypass -File araclar\trendyol_gorevi_kur.ps1
# Kaldırma:
#   Unregister-ScheduledTask -TaskName "3D Urun Bulucu - Trendyol" -Confirm:$false
#
# Görev her gün 10:00'da denenir; son analizden 7 gün geçmediyse hemen kapanır. Bilgisayar o saatte
# kapalıysa açıldığında çalışır. Pencere açılmaz; çıktı logs\trendyol.log dosyasına yazılır.

$kok = Split-Path -Parent $PSScriptRoot
$py = Join-Path $kok ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { throw "Python sanal ortamı bulunamadı: $py" }

$eylem = New-ScheduledTaskAction -Execute $py -WorkingDirectory $kok `
    -Argument "-m urun_bulucu.trendyol --telegram --zamani-geldiyse --gunluk logs\trendyol.log"
$tetik = New-ScheduledTaskTrigger -Daily -At 10:00
$ayar = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "3D Urun Bulucu - Trendyol" -Action $eylem -Trigger $tetik -Settings $ayar -Force `
    -Description "Haftada bir Trendyol 3D magaza analizi (her gun denenir, 7 gun dolmadiysa kapanir). Proje: $kok" |
    Select-Object TaskName, State
Write-Host "Kuruldu. Kayit: $kok\logs\trendyol.log"
