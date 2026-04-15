Option Explicit
Sub inCtu()
Dim fullPath As String
Dim folderPath As String ' folder chua file can in
Dim fileName As String ' tên file
Dim sheetName As String ' tên sheet trong file
Dim pageRange As String ' vùng cân in
Dim wbTarget As Workbook ' File c?n in
Dim wsTarget As Worksheet   ' sheet can in
Dim i As Long, lastRow As Long
Dim wsSave As Worksheet, wsDM As Worksheet
Dim pageNum As Long
Dim pages() As String
Dim p As Variant
Dim answer As Integer

Set wsSave = ThisWorkbook.Sheets("Save")
Set wsDM = ThisWorkbook.Sheets("DM")
lastRow = wsSave.Cells(wsSave.Rows.Count, "A").End(xlUp).row


Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False 'ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

' Đuong dân  chua file cân in
Dim actualFileName As String
folderPath = wsSave.Range("X1")

answer = MsgBox("Do you want to proceed that ?", vbYesNo) ' hien thi yes/no
Select Case answer
        Case vbYes
          For i = 2 To lastRow
            If wsSave.Range("R" & i) = wsDM.Range("K6") Then
                If wsSave.Range("C" & i) <> "" Then ' Truong hop in tkn
                    fileName = "ToKhaiHQ7N_QDTQ_" & wsSave.Range("A" & i) ' ten file cân in phai khop
                    actualFileName = Dir(folderPath & fileName & ".*") '  dùng de kiêm tra su tôn tai cua duôi file nhu xlsx, pdf...
                    pageRange = "1," & (wsSave.Range("D" & i) + 2) ' trang cân in
                    If fileName <> "" And pageRange <> "" Then ' kiem tra xem tên file và trang cân in co tôn tai ko
                          If actualFileName <> "" Then ' kiêm tra xem file có thât su tôn tai o duong dân dó không.
                            fullPath = folderPath & actualFileName 'Ghép duong dân thu muc và tên file
                              Set wbTarget = Workbooks.Open(fullPath) ' mo file lên theo duong dan gán wbtarget vào file can in dang mo
                              Set wsTarget = wbTarget.Sheets("TKN") ' lay sheet can in
                              
                              ' Tách các trang (vd: "1,5")
                              pages = Split(Replace(pageRange, " ", ""), ",")
                              
                              'in trang p
                              For Each p In pages
                                pageNum = Val(p)
                                  If pageNum > 0 Then ' bây loi
                                      wsTarget.PrintOut From:=pageNum, To:=pageNum
                                  End If
                              Next p
                              
                              ' Đóng file sau khi in
                              wbTarget.Close SaveChanges:=False
                              Set wsTarget = Nothing ' giai phóng bô nho
                  
                          Else
                              MsgBox "Không t́m thây file: " & fullPath, vbExclamation
                          End If
                      End If
                      
                Else '  truong hop in hd VAT = file PDF
                
                    Dim PDFSoftWarePath As String ' duong dan chua phan mem pdf
                    Dim shellCmd As String ' cau lenh dùng de in file pdf
                   
                    PDFSoftWarePath = wsSave.Range("Y1") ' chinh theo duong dan phan mem PDF thuc te máy ban
                    fileName = wsSave.Range("A" & i) ' ten file cân in phai khop, clng chuyen sang kieu seri ngày
                    If Right(fileName, 4) <> ".pdf" Then fileName = fileName & ".pdf" 'dam bao tên file có duôi .pdf
                    fullPath = folderPath & fileName
                    If Dir(PDFSoftWarePath) = "" Then
                        MsgBox "Đuong dan phan mêm doc PDF không hop lư: " & PDFSoftWarePath, vbExclamation
                        GoTo ContinueLoop
                    
                    Else
                        If Dir(fullPath) <> "" Then
                            shellCmd = """" & PDFSoftWarePath & """ /p /h """ & fullPath & """" 'open file PDF, /p là lenh in tài lieu ra máy in mac dinh., /h là lênh ân cua sô
                            Shell shellCmd, vbHide ' câu lenh in
                        Else
                            MsgBox "Không t́m thây file: " & fullPath, vbExclamation
                        End If
                     End If
                End If
            End If
ContinueLoop:     ' tiep tuc ṿng lap khi có lôi
    Next i
            
            
            
        Case vbNo
            MsgBox ("OK!")
    End Select

  
    
lbFinally: ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
    
End Sub


Function GetPDFViewerPath() As String
    Dim wsh As Object 'wsh: doi tuong dùng de tuong tác voi registry (WScript.Shell)
    Dim pdfAssoc As String ' luu kêt qua lênh assoc .pdf (ḍ ki?u t?p liên k?t v?i .pdf)
    Dim fileType As String ' kiêu file duoc liên k?t (ví d?: AcroExch.Document.DC)
    Dim appPath As String ' lênh thuc thi mo file PDF (ví d?: "C:\Program Files\Adobe\..." "%1")
    Dim shellOutput As String 'dùng dê luu kêt qua lênh ftype [fileType]

    On Error GoTo ErrHandler
    Set wsh = CreateObject("WScript.Shell")

    ' Bu?c 1: Lây dinh danh ?ng d?ng m? .pdf (VD: AcroExch.Document.DC ho?c FoxitReader.Document)
    pdfAssoc = CreateObject("WScript.Shell").Exec("cmd /c assoc .pdf").StdOut.ReadAll
    If InStr(pdfAssoc, "=") = 0 Then GoTo ErrHandler
    fileType = Trim(Split(pdfAssoc, "=")(1))
    
    ' Bu?c 2: L?y command m? ?ng d?ng dó
    shellOutput = CreateObject("WScript.Shell").Exec("cmd /c ftype " & fileType).StdOut.ReadAll
    If InStr(shellOutput, "=") = 0 Then GoTo ErrHandler
    appPath = Trim(Split(shellOutput, "=")(1))
    
    ' Bu?c 3: Tách l?y du?ng d?n th?c thi
    If Left(appPath, 1) = """" Then
        appPath = Mid(appPath, 2, InStr(2, appPath, """") - 2)
    Else
        appPath = Split(appPath, " ")(0)
    End If
    
    ' Tr? v? k?t qu?
    GetPDFViewerPath = appPath
    Exit Function

ErrHandler:
    GetPDFViewerPath = ""
End Function
