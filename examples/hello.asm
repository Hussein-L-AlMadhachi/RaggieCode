; hello.asm - Hello World program for 8086 training kit
; Assemble: MASM hello.asm (or TASM /masm hello.asm)
; Link:     LINK hello.obj
; Run:      hello.exe  (or load onto the trainer kit and run)

.MODEL SMALL
.STACK 100H

.DATA
    msg DB 'Hello, World!', 0DH, 0AH, '$'

.CODE
MAIN PROC
    ; initialize data segment
    MOV AX, @DATA
    MOV DS, AX

    ; print the string using DOS interrupt 21h, function 09h
    MOV AH, 09H
    LEA DX, msg
    INT 21H

    ; exit program (DOS interrupt 21h, function 4Ch)
    MOV AH, 4CH
    INT 21H
MAIN ENDP
END MAIN
