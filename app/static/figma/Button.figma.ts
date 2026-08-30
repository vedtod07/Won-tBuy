// url=https://www.figma.com/design/8lxTsOBbObdHJYuiyJZzj1/Won-tBuy-Lab-UI?node-id=5-28
// source=app/static/index.html
// component=Button
import figma from 'figma'
const instance = figma.selectedInstance
const label = instance.findText('Enter lab')
const text = label && 'textContent' in label ? label.textContent : 'Enter lab'

export default {
  example: figma.code`<button type="submit" class="btn-primary">${text}</button>`,
  imports: [],
  id: 'button-primary',
  metadata: { nestable: true },
}
