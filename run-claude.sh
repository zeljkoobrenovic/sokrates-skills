rm -rf repository

echo "Cloning $1 repository..."
git clone $1 repository

cd repository

echo "Extracting git history and initializing sokrates..."
sokrates extractGitHistory
sokrates init

sokrates addCustomTab -label "AI Insights*" -iframeLink "../ai-insights/index.html"

echo "Generating sokrates reports (initial version)..."
sokrates generateReports

cd _sokrates
git clone https://github.com/zeljkoobrenovic/sokrates-skills

cd ..

echo "Improving sokrates configuration using sokrates skills..."
claude -p "Use skills from _sokrates/sokrates-skills/config (see SKILL.md) to improve the sokrates configuration by breaking it down into clear parts and identifying important features. Improve the people setup to remove repeated contributors in commit analysis. Finish analyses in 1 minute." --allowedTools "Read,Edit,Bash" --verbose

echo "Generating sokrates reports (after configuration changes)..."
sokrates generateReports

echo "Starting full AI-Insight scan using sokrates skills..."
claude -p "Use skills from _sokrates/sokrates-skills/scanners (see SKILL.md) and do a full scan. Finish analyses in 1 minute." --allowedTools "Read,Edit,Bash" --verbose

echo "Generating summary visuals for the AI Insights report (expecting GEMINI_API_KEY system variable)..."
python3 _sokrates/sokrates-skills/skills/illustrators/generate_summary_visuals.py _sokrates/reports/ai-insights

rm -rf _sokrates/sokrates-skills

echo "Opening sokrates report in the browser..."
open _sokrates/reports/index.html