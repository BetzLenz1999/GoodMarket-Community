// Minigames JavaScript

let userWallet = null;

document.addEventListener('DOMContentLoaded', async () => {
    console.log('🎮 Minigames page loaded');
    await loadUserStats();
});

async function loadUserStats() {
    try {
        const response = await fetch('/minigames/api/user-stats');
        const data = await response.json();

        if (data.success) {
            userWallet = data.user_wallet;
            const walletBalanceEl = document.getElementById('wallet-balance');
            if (walletBalanceEl) {
                walletBalanceEl.textContent = `${userWallet.toFixed(2)} G$`;
            }

            await updateTotalEarned();
        } else {
            console.error('❌ Failed to load user stats:', data.error);
        }
    } catch (error) {
        console.error('❌ Error loading user stats:', error);
    }
}

async function updateTotalEarned() {
    console.log('📊 Fetching total earned from all sources...');

    const learnEarnResponse = await fetch('/learn-earn/quiz-history?limit=1000');
    const learnEarnData = await learnEarnResponse.json();

    const telegramResponse = await fetch('/api/daily-task/history?limit=1000');
    const telegramData = await telegramResponse.json();

    const twitterResponse = await fetch('/api/twitter-task/transaction-history?limit=1000');
    const twitterData = await twitterResponse.json();

    let learnEarnTotal = 0;
    if (learnEarnData.quiz_history && Array.isArray(learnEarnData.quiz_history)) {
        learnEarnTotal = learnEarnData.quiz_history.reduce((sum, quiz) => {
            return sum + (parseFloat(quiz.amount_g$) || 0);
        }, 0);
    }

    let telegramTotal = 0;
    if (telegramData.success && telegramData.transactions) {
        telegramTotal = telegramData.transactions
            .filter(tx => tx.status === 'completed')
            .reduce((sum, tx) => sum + (parseFloat(tx.reward_amount) || 0), 0);
    }

    let twitterTotal = 0;
    if (twitterData.success && twitterData.transactions) {
        twitterTotal = twitterData.transactions
            .filter(tx => tx.status === 'completed')
            .reduce((sum, tx) => sum + (parseFloat(tx.reward_amount) || 0), 0);
    }

    const totalEarned = learnEarnTotal + telegramTotal + twitterTotal;
    console.log('✅ Total Earned Calculated:', totalEarned, 'G$');

    const totalEarnedEl = document.getElementById('total-earned');
    if (totalEarnedEl) {
        totalEarnedEl.textContent = totalEarned.toFixed(2) + ' G$';
    }
}

window.closeGameModal = function() {
    const modal = document.getElementById('gameModal');
    if (modal) modal.style.display = 'none';
    const content = document.getElementById('gameContent');
    if (content) content.innerHTML = '';
};

function showNotification(message, type = 'info') {
    const notification = document.getElementById('notification');
    if (!notification) {
        console.error('Notification element not found!');
        return;
    }
    notification.textContent = message;
    notification.style.display = 'block';
    notification.style.background = type === 'success' ? 'rgba(16, 185, 129, 0.95)' :
                                   type === 'error' ? 'rgba(239, 68, 68, 0.95)' :
                                   'rgba(99, 102, 241, 0.95)';

    setTimeout(() => {
        notification.style.display = 'none';
    }, 3000);
}
