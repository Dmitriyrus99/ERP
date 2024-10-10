(async () => {
  setTimeout(() => {
    const button = document.querySelector('#show-icons')
    const chat = document.querySelector('erp-full-chat').shadowRoot.querySelector('#full-chat-icon-container')
    const calendar = document.querySelector('erp-calendar').shadowRoot.querySelector('#calendar-icon-container')

    button.addEventListener('click', () => {
      console.log('hide or show icons')
      chat.classList.toggle('hidden')
      calendar.classList.toggle('hidden')
      button.classList.toggle('close-icon-container')
    })
  }, 3000)
})()