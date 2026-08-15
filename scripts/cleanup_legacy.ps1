# 清理旧版/实验脚本
# 脚本位于 scripts/ 下，项目根取上一级目录
$ProjectRoot = Split-Path -Parent $PSScriptRoot

$files = @(
    "run_mineru.py",
    "src\ocr\pdf_processor.py",
    "src\ocr\pdf_processor_mineru.py",
    "src\ocr\test_ocr.py",
    "src\ocr\test_mineru.py",
    "data\tmp\ocr_test_page.png"
)

foreach ($rel in $files) {
    $path = Join-Path $ProjectRoot $rel
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
        Write-Host "已删除: $rel"
    }
    else {
        Write-Host "不存在，跳过: $rel"
    }
}

$emptyDirs = @("render_out", "config")
foreach ($rel in $emptyDirs) {
    $path = Join-Path $ProjectRoot $rel
    if (Test-Path -LiteralPath $path) {
        $items = Get-ChildItem -LiteralPath $path -Force
        if ($items.Count -eq 0) {
            Remove-Item -LiteralPath $path -Force
            Write-Host "已删除空目录: $rel"
        }
        else {
            Write-Host "目录非空，保留: $rel"
        }
    }
}
