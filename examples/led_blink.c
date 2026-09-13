/* LED blink demo for ex4.DSN (AT89C51 @ 11.0592MHz, P3.7 -> 470R -> LED) */
#include <reg52.h>

#if defined(__SDCC)
__sbit __at (0xB7) LED;
#else
sbit LED = P3^7;
#endif

void delay_ms(unsigned int ms)
{
    unsigned int i, j;
    for (i = 0; i < ms; i++)
        for (j = 0; j < 110; j++);
}

void main(void)
{
    while (1)
    {
        LED = 0;
        delay_ms(300);
        LED = 1;
        delay_ms(300);
    }
}
