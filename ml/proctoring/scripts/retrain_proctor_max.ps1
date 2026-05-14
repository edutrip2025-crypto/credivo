[CmdletBinding()]
param(
  [switch]$SkipDependencyInstall,
  [switch]$UseRelaxedDeps,
  [switch]$IncludeLibriSpeechFull,
  [string]$ExternalVideoRoot = "data\proctoring\external",
  [int]$MaxFrames = 120,
  [int]$WindowsPerVideo = 6,
  [int]$XgbEstimators = 1200,
  [int]$CnnEpochs = 180
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

$repoRoot = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$venvPython = Join-Path $repoRoot ".venv-proctoring\Scripts\python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }

function Invoke-Python {
  param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
  )
  & $pythonExe @Args
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed: $pythonExe $($Args -join ' ')"
  }
}

function Invoke-Step {
  param(
    [int]$Index,
    [int]$Total,
    [string]$Title,
    [scriptblock]$Action
  )
  $pct = [Math]::Floor((($Index - 1) * 100.0) / $Total)
  Write-Progress -Id 1 -Activity "Proctor AI max training pipeline" -Status $Title -PercentComplete $pct
  Write-Host ""
  Write-Host "[$Index/$Total] $Title" -ForegroundColor Cyan
  & $Action
}

Push-Location $repoRoot
try {
  $steps = 9
  $externalManifestPaths = @()
  $packArgs = @("--root", "data\proctoring\audio_pack", "--pack", "all", "--kaggle-unzip")
  if ($IncludeLibriSpeechFull) {
    $packArgs += "--include-librispeech-full"
  }

  Invoke-Step -Index 1 -Total $steps -Title "Install/upgrade ML dependencies" -Action {
    if ($SkipDependencyInstall) {
      Write-Host "Skipping dependency install (using existing venv packages)." -ForegroundColor Yellow
      return
    }
    Invoke-Python -m pip install --upgrade pip
    if ($UseRelaxedDeps) {
      Invoke-Python -m pip install numpy pandas scikit-learn opencv-python joblib tqdm matplotlib seaborn
    } else {
      Invoke-Python -m pip install -r "ml\proctoring\requirements.txt"
    }
    Invoke-Python -m pip install -r "ml\proctoring\requirements-optional.txt"
    Invoke-Python -m pip install kaggle huggingface_hub
  }

  Invoke-Step -Index 2 -Total $steps -Title "Download expanded dataset pack" -Action {
    Invoke-Python "ml\proctoring\scripts\download_audio_data_pack.py" @packArgs
  }

  Invoke-Step -Index 3 -Total $steps -Title "Build manifest for OEP" -Action {
    Invoke-Python "ml\proctoring\scripts\build_manifest.py" `
      --input "data\proctoring\raw" `
      --output "data\proctoring\processed\manifest_oep.csv"
  }

  Invoke-Step -Index 4 -Total $steps -Title "Build manifest for exam-cheating dataset" -Action {
    Invoke-Python "ml\proctoring\scripts\build_manifest.py" `
      --input "data\proctoring\audio_pack\kaggle\exam_cheating" `
      --output "data\proctoring\processed\manifest_exam.csv"

    $externalRootAbs = Join-Path $repoRoot $ExternalVideoRoot
    $externalManifestDir = Join-Path $repoRoot "data\proctoring\processed\external_manifests"
    if (Test-Path $externalRootAbs) {
      New-Item -ItemType Directory -Path $externalManifestDir -Force | Out-Null
      foreach ($dir in Get-ChildItem -Path $externalRootAbs -Directory) {
        $safeName = ($dir.Name -replace "[^a-zA-Z0-9_\-]", "_")
        $manifestOut = Join-Path $externalManifestDir ("manifest_" + $safeName + ".csv")
        try {
          Invoke-Python "ml\proctoring\scripts\build_manifest.py" `
            --input $dir.FullName `
            --output $manifestOut
          $externalManifestPaths += $manifestOut
        }
        catch {
          Write-Host "Skipping external dataset folder with no media/invalid structure: $($dir.FullName)" -ForegroundColor Yellow
        }
      }
    }
  }

  Invoke-Step -Index 5 -Total $steps -Title "Merge manifests and deduplicate" -Action {
    $mergeInputs = @(
      "data\proctoring\processed\manifest_oep.csv",
      "data\proctoring\processed\manifest_exam.csv"
    ) + $externalManifestPaths
    Invoke-Python "ml\proctoring\scripts\merge_manifests.py" `
      --inputs @mergeInputs `
      --output "data\proctoring\processed\manifest.csv"
  }

  Invoke-Step -Index 6 -Total $steps -Title "Auto-label mixed manifest (safe override for OEP video naming)" -Action {
    Invoke-Python "ml\proctoring\scripts\auto_label_oep.py" `
      --manifest "data\proctoring\processed\manifest.csv" `
      --output "data\proctoring\processed\manifest_labeled.csv"
  }

  Invoke-Step -Index 7 -Total $steps -Title "Analyze dataset coverage gaps" -Action {
    Invoke-Python "ml\proctoring\scripts\analyze_dataset_gaps.py" `
      --manifest "data\proctoring\processed\manifest_labeled.csv" `
      --output "data\proctoring\processed\dataset_gap_report.json"
  }

  Invoke-Step -Index 8 -Total $steps -Title "Extract richer video features (shows tqdm progress bar)" -Action {
    Invoke-Python "ml\proctoring\scripts\extract_video_features.py" `
      --manifest "data\proctoring\processed\manifest_labeled.csv" `
      --output "data\proctoring\processed\video_features_labeled.csv" `
      --max-frames $MaxFrames `
      --windows-per-video $WindowsPerVideo
  }

  Invoke-Step -Index 9 -Total $steps -Title "Train supervised models (long-run settings)" -Action {
    Invoke-Python "ml\proctoring\scripts\train_supervised_models.py" `
      --features "data\proctoring\processed\video_features_labeled.csv" `
      --out-dir "data\proctoring\models\supervised" `
      --xgb-estimators $XgbEstimators `
      --cnn-epochs $CnnEpochs
  }

  Write-Progress -Id 1 -Activity "Proctor AI max training pipeline" -Completed
  Write-Host ""
  Write-Host "Completed. Outputs:" -ForegroundColor Green
  Write-Host " - data\proctoring\processed\dataset_gap_report.json"
  Write-Host " - data\proctoring\processed\video_features_labeled.csv"
  Write-Host " - data\proctoring\models\supervised\supervised_bundle.joblib"
  Write-Host " - data\proctoring\models\supervised\evaluation_report.json"
  Write-Host " - data\proctoring\models\supervised\deduction_rules.json"
}
finally {
  Pop-Location
}
