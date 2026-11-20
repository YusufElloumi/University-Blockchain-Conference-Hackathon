## Inspiration
- We come from a very competitive friend group. For years, we've kept a running win/loss tally across everything from video games and sports to fitness and academics.
- We believe you're the average of the five people you spend the most time with. We wanted to turn that idea into a platform where friends push each other to improve through healthy competition and accountability.


## What it does
- Rival turns fitness into a competition where friends contribute USDC entry fees, earn points through Oura-synced workouts, and compete for an automatically distributed prize pool.
- It supports four competition formats: winner-takes-all, podium, goals, and teams, with events ranging from 15 minutes to 365 days.
- Competition rules are locked onchain before participants join, while personal fitness data stays private. Users sign up with just an email, with wallets and transactions managed in the background.
- Recreational and beer-league teams compete to earn the most points based on customizable league rules, with bonus points available through Gemini Prediction Markets.

## How we built it
- We built a Solana smart contract using Rust and Anchor to manage prize pools, lock competition rules, and verify signed results before payouts.
- We integrated Privy for email authentication and embedded wallets, alongside automated gas funding so users never have to interact with crypto infrastructure.
- Our frontend uses React and Vite, while the backend is built with Python FastAPI and Neon Postgres, hosted on Render.
- We integrated QuickNode Streams to listen for onchain events and deliver real-time updates through webhooks.
- We built an Oura OAuth integration and a custom Proof of Sweat scoring engine that considers workout duration, effort, and evidence quality.
- We integrated the Gemini Prediction Markets API to introduce pick-based bonus rounds.
- Throughout development, we leveraged Claude Code and Grok as agentic coding assistants.


## Challenges we ran into
- We initially explored Strava but ran into subscription requirements and restrictive API terms, including limitations around data visibility and AI usage.
- Oura's OAuth implementation required a custom three-step authentication flow because the authorization redirect did not preserve the user's login session.
- We wanted to implement Solana Confidential Compute for private fitness scoring, but the lack of a publicly available SDK and devnet program prevented us from integrating TEEs during the hackathon.
- We also encountered public devnet RPC rate limits while learning Rust and Anchor from scratch.

## Accomplishments we're proud of
- We made crypto practically invisible to users through email sign-in, embedded wallets, and automated gas funding, eliminating seed phrases and gas prompts.
- We implemented onchain competition rules and payout conditions, ensuring that event outcomes are governed by predefined smart contract logic.
- We developed a working Oura integration and an explainable Proof of Sweat scoring engine that generates downloadable, independently verifiable results.
- We brought everything together into a polished, end-to-end product with a publicly accessible website.


## What we learned
- We learned that iterating quickly and testing ideas can lead to significantly better products than trying to plan every detail upfront.
- We discovered how third-party API restrictions can fundamentally shape product architecture and force us to explore alternative solutions.
- We learned how to balance privacy and transparency by keeping sensitive fitness data offchain while making competition outcomes independently verifiable.
- We gained hands-on experience connecting authentication, external APIs, blockchain infrastructure, and smart contracts into one cohesive application.

## What's next for Rival
- Once live, Rival will support real USDC deposits and yield-generating prize pools through Jupiter Lend.
- We plan to move fitness scoring into Solana Confidential Compute using Trusted Execution Environments (TEEs) once publicly accessible infrastructure becomes available.
- We're looking to expand our fitness integrations to include Strava, Apple Health, and Runna.
- We want to bring Rival to mobile to make workout tracking and competition more seamless.
- Most importantly, we plan to officially launch with targeting to recreational and beer-league teams, using player statistics and prediction markets to bring healthy competition and accountability into existing communities.
