import typer

app = typer.Typer(
    help="Connect USB drive on the CAN Switcher to the PC or to the ECU.",
    no_args_is_help=True
)

@app.command()
def connect(target: str = typer.Argument(..., help="Target to connect to: 'pc' or 'ecu'")):
    """
    Connect the USB drive to the specified target.
    """
    target = target.lower()
    if target == "pc":
        """Connect the USB drive to the Pi."""
        from usb_switcher import UsbSwitcher

        UsbSwitcher().connect_peripheral_to_pi()
    elif target == "ecu":
        """Connect the USB drive to the ECU."""
        from usb_switcher import UsbSwitcher

        UsbSwitcher().connect_peripheral_to_external()
    else:
        typer.echo("Invalid target. Please choose 'pc' or 'ecu'.", err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
