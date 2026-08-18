# 매일 09:00 자동 실행 작업 등록 (관리자 PowerShell에서 1회 실행)
# 실행: powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1

$bat = Join-Path $PSScriptRoot "run_daily.bat"
$action  = New-ScheduledTaskAction -Execute $bat
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable

Register-ScheduledTask -TaskName "PesticideMonitorDaily" `
  -Action $action -Trigger $trigger -Settings $settings `
  -Description "수출농산물 농약기준 모니터링: 매일 09시 수집·비교·보고·알림" -Force

Write-Host "등록 완료: PesticideMonitorDaily (매일 09:00)"
Write-Host "확인:  Get-ScheduledTask -TaskName PesticideMonitorDaily"
Write-Host "즉시 테스트:  Start-ScheduledTask -TaskName PesticideMonitorDaily"
