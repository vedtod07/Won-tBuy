// url=https://www.figma.com/design/8lxTsOBbObdHJYuiyJZzj1/Won-tBuy-Lab-UI?node-id=5-13
// source=app/static/index.html
// component=LoginForm
import figma from 'figma'

export default {
  example: figma.code`
    <form id="login-form" class="login-card">
      <h2>Enter the lab</h2>
      <p class="sub">No OAuth. Name and email stay on this machine.</p>
      <div class="field">
        <label for="login-name">Name</label>
        <input id="login-name" required>
      </div>
      <div class="field">
        <label for="login-email">Email</label>
        <input id="login-email" type="email" required>
      </div>
      <button type="submit" class="btn-primary">Enter lab</button>
      <button type="button" class="btn-ghost" id="login-judge">Continue as judge</button>
    </form>
  `,
  imports: [],
  id: 'login-form',
  metadata: { nestable: false },
}
