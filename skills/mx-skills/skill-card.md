## Description: <br>
Provides an Eastmoney Miaoxiang financial skill collection for financial data lookup, financial search, stock screening, watchlist management, and simulated portfolio management, with MX_APIKEY authentication required. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[QQK000](https://clawhub.ai/user/QQK000) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
External users, developers, and finance-focused agents use this skill to install Eastmoney Miaoxiang subskills for market data, financial search, stock screening, watchlist operations, and simulated portfolio workflows that require MX_APIKEY. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Remote archive installation may add unreviewed files to the local skill directory. <br>
Mitigation: Install only after reviewing the archive sources and verifying downloaded files independently. <br>
Risk: The wildcard removal command can delete existing mx-skills directories before installation. <br>
Mitigation: Back up existing ~/.openclaw/skills/mx-skills* folders and prefer explicit paths over wildcard deletion. <br>
Risk: MX_APIKEY is required for authentication and could be exposed if logged, shared, or committed. <br>
Mitigation: Treat MX_APIKEY as a secret and set it only in trusted sessions or secret-management tooling. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/QQK000/mx-skills) <br>
- [Publisher profile](https://clawhub.ai/user/QQK000) <br>
- [Eastmoney Miaoxiang Skills page](https://dl.dfcfs.com/m/itc4) <br>


## Skill Output: <br>
**Output Type(s):** [text, markdown, shell commands, configuration, guidance] <br>
**Output Format:** [Markdown installation and usage guidance with shell command examples] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Requires MX_APIKEY; installation downloads remote archives and writes skill files under ~/.openclaw/skills/mx-skills.] <br>

## Skill Version(s): <br>
1.0.2 (source: server release metadata; artifact frontmatter lists 1.0.0) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
