# setup.ps1 — One-time dev environment setup for Bleacher Bot (Windows)

Write-Host "Setting up Bleacher Bot development environment..." -ForegroundColor Cyan

# Create virtual environment
python -m venv .venv
Write-Host "✓ Created .venv" -ForegroundColor Green

# Activate and install deps
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Write-Host "✓ Dependencies installed" -ForegroundColor Green

# Copy .env template if no .env exists
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "✓ Copied .env.example → .env  (fill in your credentials)" -ForegroundColor Yellow
} else {
    Write-Host "  .env already exists, skipping." -ForegroundColor Gray
}

Write-Host ""
Write-Host "Setup complete! To activate the venv in a new shell run:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host ""
Write-Host "Then do a dry run:" -ForegroundColor Cyan
Write-Host "  `$env:DRY_RUN='true'; python main.py" -ForegroundColor White
