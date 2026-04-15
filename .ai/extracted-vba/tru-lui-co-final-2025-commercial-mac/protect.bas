Sub unProtected()
Dim wsCurrent As Worksheet
Set wsCurrent = ActiveSheet ' Luu l?i sheet dang hi?n th?
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual
        ThisWorkbook.Sheets("X-N").Unprotect "141013"
        ThisWorkbook.Sheets("LVC").Unprotect "141013"
        ThisWorkbook.Sheets("RVC").Unprotect "141013"
        ThisWorkbook.Sheets("EUR1").Unprotect "141013"
        ThisWorkbook.Sheets("CTH").Unprotect "141013"
        ThisWorkbook.Sheets("CTSH").Unprotect "141013"
        
        wsCurrent.Activate ' Quay l?i sheet ban d?u ' Quay l?i sheet ban d?u
    
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
End Sub

Sub protected()
Dim wsCurrent As Worksheet
Set wsCurrent = ActiveSheet ' Luu l?i sheet dang hi?n th?
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual
    
        ThisWorkbook.Sheets("X-N").protect "141013"
        ThisWorkbook.Sheets("LVC").protect "141013"
        ThisWorkbook.Sheets("RVC").protect "141013"
        ThisWorkbook.Sheets("EUR1").protect "141013"
        ThisWorkbook.Sheets("CTH").protect "141013"
        ThisWorkbook.Sheets("CTSH").protect "141013"
        
        wsCurrent.Activate ' Quay l?i sheet ban d?u
    
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic

End Sub
