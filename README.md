# qt-dlp: interfaz gráfica para yt-dlp escrita en Qt

![Captura de pantalla](img/Captura de pantalla.png)


qt-dlp es una interfaz gráfica para yt-dlp. El motivo de crearla fue que quería una app en Qt (no GTK) que hiciera de interfaz de yt-dlp para mi uso personal. Básicamente hace lo siguiente:

* Descarga directa: equivalente a `yt-dlp "ENLACE-AL-VÍDEO"`.
* Pedir formatos: equivalente a `yt-dlp -F "ENLACE-AL-VÍDEO"`. 
* Muestra las opciones de vídeo y audio para elegir entre ellos. Al finalizar los une con FFmpeg.
* Primero intentará descargar sin cookies. Si falla, directamente lo intentará con las cookies de un navegador a elegir entre los ajustes.

Para que funcione qt-dlp tiene que estar instalado y en el PATH:

* yt-dlp
* ffmpeg
* pyqt6

## Escrita con IA

Cabe destacar que esta app se ofrece como tal, sin demasiadas garantías (aunque a mí me funciona). Como no la necesitaba demasiado, le pedí a DeepSeek que me creara lo que buscaba. Poco a poco fue afinándola hasta tener lo que hay aquí.

