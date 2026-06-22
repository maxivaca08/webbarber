const DIAS  = ['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'];
const MESES = ['','enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];

function parseDate(s: string) {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function fechaCorta(s: string) {
  const d = parseDate(s);
  return `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')}/${d.getFullYear()}`;
}

export function diaSemana(s: string) {
  return DIAS[parseDate(s).getDay()];
}

export function fechaLarga(s: string) {
  const d = parseDate(s);
  return `${DIAS[d.getDay()]} ${d.getDate()} de ${MESES[d.getMonth()+1]}`;
}

export function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
